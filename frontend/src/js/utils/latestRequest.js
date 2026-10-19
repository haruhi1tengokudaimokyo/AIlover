/**
 * 递增请求 id 守卫：解决无限滚动/搜索重置场景下的重复请求与过期响应竞态。
 * 用法：发起请求前 const seq = guard.next()；响应到达时 if (!guard.isLatest(seq)) 丢弃。
 * reset/卸载时调用 invalidate() 让所有在途响应失效。
 */
export function createLatestRequest() {
  let current = 0
  return {
    next() {
      return ++current
    },
    isLatest(id) {
      return id === current
    },
    invalidate() {
      current++
    },
  }
}
