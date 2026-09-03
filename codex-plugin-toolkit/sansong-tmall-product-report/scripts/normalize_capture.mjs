#!/usr/bin/env node
import fs from 'node:fs'

const input = process.argv[2]
if (!input) {
  console.error('Usage: node scripts/normalize_capture.mjs <capture.json>')
  process.exit(1)
}

const payload = JSON.parse(fs.readFileSync(input, 'utf8'))
const raw = payload.raw || payload.structured || payload
const images = raw.images || raw.image_groups || {}
const product = raw.product || {}
const sales = raw.sales || {}

const out = {
  schemaVersion: '9.0.0',
  category: raw.category || {candidates: raw.categoryCandidates || [], breadcrumb: raw.breadcrumb || []},
  product: {
    itemId: product.itemId || raw.itemId || '',
    skuId: product.skuId || raw.skuId || '',
    title: product.title || raw.title || payload.title || '',
    shop: product.shop || raw.shopName || '',
    brand: product.brand || '',
    category: product.category || raw.categoryName || '',
    url: product.url || raw.url || payload.url || ''
  },
  sales: {
    currentPrice: sales.currentPrice || raw.price || '',
    sold: sales.sold || raw.sold || '',
    ranking: sales.ranking || ''
  },
  counts: {
    attributes: Array.isArray(raw.attributes) ? raw.attributes.length : 0,
    sku: Array.isArray(raw.sku) ? raw.sku.length : 0,
    promotions: Array.isArray(raw.promotions) ? raw.promotions.length : 0,
    reviews: Array.isArray(raw.reviews) ? raw.reviews.length : 0,
    questions: Array.isArray(raw.questions) ? raw.questions.length : 0,
    mainImages: Array.isArray(images.main || images.hero) ? (images.main || images.hero).length : 0,
    detailImages: Array.isArray(images.detail) ? images.detail.length : 0,
    skuImages: Array.isArray(images.sku) ? images.sku.length : 0,
    buyerShowImages: Array.isArray(images.buyerShow || images.review) ? (images.buyerShow || images.review).length : 0
  },
  attributes: raw.attributes || [],
  sku: raw.sku || [],
  promotions: raw.promotions || [],
  reviews: raw.reviews || [],
  questions: raw.questions || [],
  images
}

console.log(JSON.stringify(out, null, 2))
