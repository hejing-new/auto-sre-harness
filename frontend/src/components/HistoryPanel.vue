<script setup>
import { ref, computed } from "vue"
import { marked } from "marked"
import { useHistory } from "@/composables/useHistory"

const {
  records, total, loading, error,
  selectedRecord, detailLoading,
  loadList, loadDetail, clearSelection
} = useHistory()

const showModal = ref(false)

function viewReport(taskId) {
  loadDetail(taskId)
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  clearSelection()
}

function refresh() {
  loadList()
}

const renderedAnalysis = computed(() => {
  if (!selectedRecord.value || !selectedRecord.value.final_analysis) return ""
  return marked.parse(selectedRecord.value.final_analysis)
})

function statusClass(status) {
  if (status === "success") return "bg-cyber-success/20 text-cyber-success border-cyber-success/30"
  return "bg-cyber-error/20 text-cyber-error border-cyber-error/30"
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex items-center justify-between px-4 py-2 border-b border-cyber-border bg-cyber-darker/30">
      <div class="flex items-center gap-3">
        <span class="text-cyber-primary font-bold text-sm">HISTORY</span>
        <span class="text-xs text-gray-500">{{ total }} records</span>
      </div>
      <button @click="refresh" :disabled="loading" class="text-xs text-gray-400 hover:text-cyber-primary disabled:opacity-50 transition-colors">[REFRESH]</button>
    </div>
    <div class="flex-1 overflow-y-auto">
      <table class="w-full text-sm">
        <thead class="sticky top-0 bg-cyber-darker z-10">
          <tr class="text-left text-xs text-gray-500 border-b border-cyber-border">
            <th class="px-4 py-2 font-medium">TIME</th>
            <th class="px-4 py-2 font-medium">ALERT</th>
            <th class="px-4 py-2 font-medium">STEPS</th>
            <th class="px-4 py-2 font-medium">STATUS</th>
            <th class="px-4 py-2 font-medium text-right">ACTION</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rec in records" :key="rec.task_id" class="grid-row border-b border-cyber-border/50 transition-colors cursor-pointer" @click="viewReport(rec.task_id)">
            <td class="px-4 py-2 text-gray-400 text-xs font-mono">{{ rec.timestamp }}</td>
            <td class="px-4 py-2 text-gray-200 max-w-xs truncate">{{ rec.alert }}</td>
            <td class="px-4 py-2 text-gray-400 text-xs">{{ rec.total_steps || 0 }} steps | <span class="text-cyber-success">{{ rec.commands_executed || 0 }}</span> / <span class="text-cyber-error">{{ rec.commands_blocked || 0 }}</span></td>
            <td class="px-4 py-2"><span :class="statusClass(rec.status)" class="text-xs px-2 py-0.5 rounded border">{{ rec.status }}</span></td>
            <td class="px-4 py-2 text-right"><button @click.stop="viewReport(rec.task_id)" class="text-xs text-cyber-primary hover:text-cyber-accent transition-colors">VIEW</button></td>
          </tr>
          <tr v-if="records.length === 0 && !loading"><td colspan="5" class="px-4 py-12 text-center text-gray-600 text-sm">No diagnosis records yet</td></tr>
          <tr v-if="loading"><td colspan="5" class="px-4 py-12 text-center text-gray-500 text-sm">Loading...</td></tr>
        </tbody>
      </table>
    </div>
    <Teleport to="body">
      <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center modal-backdrop" @click.self="closeModal">
        <div class="w-full max-w-3xl max-h-[85vh] bg-cyber-dark border border-cyber-border rounded-lg shadow-2xl flex flex-col m-4">
          <div class="flex items-center justify-between px-5 py-3 border-b border-cyber-border">
            <span class="text-cyber-primary font-bold text-sm">RCA REPORT</span>
            <button @click="closeModal" class="text-gray-500 hover:text-cyber-accent text-lg transition-colors">&times;</button>
          </div>
          <div class="flex-1 overflow-y-auto p-5">
            <div v-if="detailLoading" class="flex items-center justify-center py-12 text-gray-500">Loading report...</div>
            <div v-else-if="selectedRecord" class="space-y-4">
              <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                <div class="bg-cyber-card border border-cyber-border rounded p-2"><span class="text-gray-500 block">TASK ID</span><span class="text-cyber-primary font-mono">{{ selectedRecord.task_id }}</span></div>
                <div class="bg-cyber-card border border-cyber-border rounded p-2"><span class="text-gray-500 block">TIME</span><span class="text-gray-200">{{ selectedRecord.timestamp }}</span></div>
                <div class="bg-cyber-card border border-cyber-border rounded p-2"><span class="text-gray-500 block">STEPS</span><span class="text-gray-200">{{ selectedRecord.total_steps || 0 }}</span></div>
                <div class="bg-cyber-card border border-cyber-border rounded p-2"><span class="text-gray-500 block">STATUS</span><span :class="selectedRecord.status === 'success' ? 'text-cyber-success' : 'text-cyber-error'">{{ selectedRecord.status }}</span></div>
              </div>
              <div class="bg-cyber-card border border-cyber-border rounded p-3"><span class="text-xs text-gray-500 block mb-1">ALERT</span><span class="text-gray-200 text-sm">{{ selectedRecord.alert }}</span></div>
              <div class="bg-cyber-card border border-cyber-border rounded p-4"><span class="text-xs text-gray-500 block mb-2">RCA ANALYSIS</span><div class="rca-markdown text-gray-300 text-sm leading-relaxed" v-html="renderedAnalysis"></div></div>
              <div v-if="selectedRecord.error" class="bg-cyber-error/10 border border-cyber-error/30 rounded p-3 text-cyber-error text-sm">{{ selectedRecord.error }}</div>
            </div>
            <div v-else class="text-gray-500 text-center py-12">No data</div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.rca-markdown :deep(h1) { color: var(--cyber-primary); font-size: 1.25rem; font-weight: bold; margin: 1rem 0 0.5rem; }
.rca-markdown :deep(h2) { color: var(--cyber-primary); font-size: 1.1rem; font-weight: bold; margin: 1rem 0 0.5rem; }
.rca-markdown :deep(h3) { color: var(--cyber-accent); font-size: 1rem; font-weight: bold; margin: 0.75rem 0 0.5rem; }
.rca-markdown :deep(p) { margin: 0.5rem 0; }
.rca-markdown :deep(ul), .rca-markdown :deep(ol) { padding-left: 1.5rem; margin: 0.5rem 0; }
.rca-markdown :deep(li) { margin: 0.25rem 0; }
.rca-markdown :deep(code) { background: rgba(0, 240, 255, 0.1); padding: 0.125rem 0.375rem; border-radius: 0.25rem; font-size: 0.85em; }
.rca-markdown :deep(pre) { background: rgba(0, 0, 0, 0.4); padding: 0.75rem; border-radius: 0.375rem; overflow-x: auto; margin: 0.5rem 0; }
.rca-markdown :deep(blockquote) { border-left: 3px solid var(--cyber-primary); padding-left: 1rem; color: var(--cyber-warning); }
.rca-markdown :deep(strong) { color: var(--cyber-accent); }
.rca-markdown :deep(a) { color: var(--cyber-primary); text-decoration: underline; }
</style>
