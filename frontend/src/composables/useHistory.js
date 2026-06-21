import { ref, readonly } from "vue"
import { fetchHistoryList, fetchHistoryDetail } from "@/api"

export function useHistory() {
  const records = ref([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref(null)
  const selectedRecord = ref(null)
  const detailLoading = ref(false)

  async function loadList(limit = 50, offset = 0) {
    loading.value = true
    error.value = null
    try {
      const data = await fetchHistoryList(limit, offset)
      records.value = data.records || []
      total.value = data.total || 0
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function loadDetail(taskId) {
    detailLoading.value = true
    selectedRecord.value = null
    try {
      selectedRecord.value = await fetchHistoryDetail(taskId)
    } catch (e) {
      error.value = e.message
    } finally {
      detailLoading.value = false
    }
  }

  function clearSelection() {
    selectedRecord.value = null
  }

  return {
    records: readonly(records),
    total: readonly(total),
    loading: readonly(loading),
    error: readonly(error),
    selectedRecord: readonly(selectedRecord),
    detailLoading: readonly(detailLoading),
    loadList,
    loadDetail,
    clearSelection
  }
}
