window.addEventListener('message',event=>{
  if(event.source!==window||event.data?.type!=='SANSONG_COLLECTOR_PING')return
  chrome.runtime.sendMessage({type:'SANSONG_COLLECTOR_WAKE'},response=>{
    window.postMessage({type:'SANSONG_COLLECTOR_PONG',requestId:event.data.requestId,installed:true,version:chrome.runtime.getManifest().version,connected:Boolean(response?.connected)},'*')
  })
})
