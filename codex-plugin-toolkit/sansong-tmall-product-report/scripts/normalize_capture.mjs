#!/usr/bin/env node
import fs from 'node:fs'

const input = process.argv[2]
if (!input) {
  console.error('Usage: node scripts/normalize_capture.mjs <capture.json>')
  process.exit(1)
}

const payload = JSON.parse(fs.readFileSync(input, 'utf8'))
const isObject = value => value && typeof value === 'object' && !Array.isArray(value)
const asArray = value => Array.isArray(value) ? value : []
const text = value => value == null ? '' : String(value)
const first = (...values) => values.find(value => value !== undefined && value !== null && text(value).trim() !== '') ?? ''
const unique = values => {
  const seen = new Set()
  return asArray(values).filter(value => {
    const key = typeof value === 'string' ? value : JSON.stringify(value)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}
const imageUrl = value => {
  if (isObject(value)) value = first(value.url, value.picUrl, value.imageUrl, value.src, value.bigUrl, value.thumbnail)
  value = text(value).trim().replace(/&amp;/g, '&')
  if (value.startsWith('//')) value = `https:${value}`
  return /^(?:https?:\/\/|data:image\/)/i.test(value) ? value : ''
}
const imageList = value => unique(asArray(value).map(imageUrl).filter(Boolean))

// Accept the three payload shapes emitted by the browser collector and by
// earlier toolkit releases: {raw}, {structured}, or a raw object.
const raw = isObject(payload?.raw)
  ? payload.raw
  : isObject(payload?.structured)
    ? payload.structured
    : (isObject(payload) ? payload : {})

const sourceProduct = isObject(raw.product) ? raw.product : {}
const sourceSales = isObject(raw.sales) ? raw.sales : {}
const sourceCategory = isObject(raw.category)
  ? raw.category
  : {candidates: asArray(raw.categoryCandidates), breadcrumb: asArray(raw.breadcrumb)}
const sourceImages = isObject(raw.images)
  ? raw.images
  : (isObject(raw.image_groups) ? raw.image_groups : {})
const sourceMeta = {
  ...(isObject(payload?.meta) ? payload.meta : {}),
  ...(isObject(raw.meta) ? raw.meta : {})
}
const sourceCollection = {
  ...(isObject(payload?.collection) ? payload.collection : {}),
  ...(isObject(raw.collection) ? raw.collection : {})
}

// Keep metadata useful for the report/audit pipeline while dropping accidental
// credentials if a collector passed through a page-level metadata object.
const sensitiveMeta = /(?:authorization|cookie|password|secret|token|api[_-]?key)/i
const meta = Object.fromEntries(Object.entries(sourceMeta).filter(([key]) => !sensitiveMeta.test(key)))
const sourceProvenance = asArray(sourceImages.provenance).map(record => {
  if (!isObject(record)) return null
  const url = imageUrl(record.url || record)
  return url ? {...record, url} : null
}).filter(Boolean)
const hasStrictSource = sourceMeta.imageClassificationVersion === 'strict-v1' && sourceProvenance.length > 0

const imageGroups = {
  ...sourceImages,
  all: imageList(sourceImages.all),
  main: imageList(sourceImages.main).length ? imageList(sourceImages.main) : imageList(sourceImages.hero),
  detail: imageList(sourceImages.detail),
  sku: imageList(sourceImages.sku),
  buyerShow: imageList(sourceImages.buyerShow).length ? imageList(sourceImages.buyerShow) : imageList(sourceImages.review),
  provenance: sourceProvenance,
  classification: isObject(sourceImages.classification) ? sourceImages.classification : {}
}
if (!imageGroups.all.length) {
  imageGroups.all = unique([
    ...imageGroups.main,
    ...imageGroups.detail,
    ...imageGroups.sku,
    ...imageGroups.buyerShow
  ])
}
if (!imageGroups.provenance.length) {
  // Legacy collectors already separated the groups; retain that evidence with
  // explicit provenance rather than silently dropping all images downstream.
  imageGroups.provenance = [
    ...imageGroups.main.map(url => ({url, group: 'main', source: 'legacy_group_main'})),
    ...imageGroups.detail.map(url => ({url, group: 'detail', source: 'legacy_group_detail'})),
    ...imageGroups.sku.map(url => ({url, group: 'sku', source: 'legacy_group_sku'})),
    ...imageGroups.buyerShow.map(url => ({url, group: 'buyerShow', source: 'review_record'}))
  ]
}
const imagePolicy = hasStrictSource ? 'strict-v1' : (imageGroups.provenance.length ? 'legacy-review-only' : '')
if (!isObject(imageGroups.classification) || !imageGroups.classification.version) {
  imageGroups.classification = {
    version: imagePolicy,
    classifiedCount: imageGroups.all.length,
    groupsAreDisjoint: true
  }
}
if (imagePolicy && !hasStrictSource) imageGroups.classification.version = imagePolicy

const product = {
  ...sourceProduct,
  itemId: first(sourceProduct.itemId, raw.itemId, payload?.itemId),
  skuId: first(sourceProduct.skuId, raw.skuId, payload?.skuId),
  title: first(sourceProduct.title, raw.title, payload?.title),
  shop: first(sourceProduct.shop, raw.shopName, payload?.shop),
  brand: first(sourceProduct.brand, raw.brand, payload?.brand),
  category: first(sourceProduct.category, raw.categoryName, payload?.category),
  url: first(sourceProduct.url, raw.url, payload?.url)
}
const parameterCollection = sourceProduct.parameterCollection ?? raw.parameterCollection ?? payload?.parameterCollection
if (isObject(parameterCollection)) product.parameterCollection = parameterCollection

const sales = {
  ...sourceSales,
  currentPrice: first(sourceSales.currentPrice, raw.price, payload?.price),
  originalPrice: first(sourceSales.originalPrice, raw.originalPrice, payload?.originalPrice),
  sold: first(sourceSales.sold, raw.sold, payload?.sold),
  ranking: first(sourceSales.ranking, raw.ranking, payload?.ranking)
}

const collection = {...sourceCollection}
if (collection.reviewCollectionComplete == null) {
  collection.reviewCollectionComplete = collection.reviewCompleteness === 'confirmed'
}
if (!collection.reviewCompleteness) {
  collection.reviewCompleteness = collection.reviewCollectionComplete ? 'confirmed' : 'unconfirmed'
}
meta.collectorVersion = first(meta.collectorVersion, '9.3.0')
if (!collection.collectorVersion) collection.collectorVersion = meta.collectorVersion
if (!hasStrictSource && meta.imageClassificationVersion === 'strict-v1') meta.imageClassificationVersion = 'legacy-v1'
if (!meta.imageClassificationVersion) meta.imageClassificationVersion = hasStrictSource ? 'strict-v1' : 'legacy-v1'
if (!meta.url && product.url) meta.url = product.url

const out = {
  schemaVersion: '9.3.0',
  meta,
  category: sourceCategory,
  product,
  sales,
  counts: {
    attributes: asArray(raw.attributes).length,
    sku: asArray(raw.sku).length,
    promotions: asArray(raw.promotions).length,
    reviews: asArray(raw.reviews).length,
    questions: asArray(raw.questions).length,
    mainImages: imageGroups.main.length,
    detailImages: imageGroups.detail.length,
    skuImages: imageGroups.sku.length,
    buyerShowImages: imageGroups.buyerShow.length
  },
  attributes: asArray(raw.attributes),
  sku: asArray(raw.sku),
  promotions: asArray(raw.promotions),
  reviews: asArray(raw.reviews),
  questions: asArray(raw.questions),
  images: imageGroups,
  collection
}

const pageText = first(raw.pageText, payload?.pageText)
if (pageText) out.pageText = text(pageText).slice(0, 120000)
const monitoring = asArray(raw.monitoring).length ? asArray(raw.monitoring) : asArray(payload?.monitoring)
if (monitoring.length) out.monitoring = monitoring

console.log(JSON.stringify(out, null, 2))
