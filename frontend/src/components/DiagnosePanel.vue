<script setup>
import { ref, computed } from "vue"
import { useHistory } from "@/composables/useHistory"

const { records, total, loading, error, loadList } = useHistory()

const alertInput = ref("")
const containerInput = ref("auto-sre-sandbox")
const maxIter = ref(10)

const emit = defineEmits(["start-diagnose"])

function onSubmit() {
  if (!alertInput.value.trim()) return
  emit("start-diagnose", {
    alert: alertInput.value.trim(),
    container: containerInput.value.trim() || "auto-sre-sandbox",
    maxIterations: maxIter.value
  })
}

const statusClass = (status) => {
  if (status === "success") return "text-cyber-success"
  return "text-cyber-error"
}

const formatTime = (ts) => {
  if (!ts) return ""
  return ts.split(" ")[1] || ts
}

loadList()
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Alert input form -->
    <div class="p-4 border-b border-cyber-border bg-cyber-darker/30">
      <div class="flex flex-wrap gap-3 items-end">
        <div class="flex-1 min-w-[200px]">
          <label class="block text-xs text-cyber-primary mb-1">ALERT</label>
          <input
            v-model="alertInput"
            type="text"
            placeholder="e.g. CPU usage > 90% on prod-server-01"
            class="w-full bg-cyber-darker border border-cyber-border rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:border-cyber-primary focus:outline-none focus:ring-1 focus:ring-cyber-primary/50 transition-colors"
            @keyup.enter="onSubmit"
          />
        </div>
        <div class="w-44">
          <label class="block text-xs text-cyber-primary mb-1">CONTAINER</label>
          <input
            v-model="containerInput"
            type="text"
            class="w-full bg-cyber-darker border border-cyber-border rounded px-3 py-2 text-sm text-gray-100 focus:border-cyber-primary focus:outline-none transition-colors"
          />
        </div>
        <div class="w-28">
          <label class="block text-xs text-cyber-primary mb-1">MAX ITER</label>
          <input
            v-model.number="maxIter"
            type="number"
            min="1"
            max="50"
            class="w-full bg-cyber-darker border border-cyber-border rounded px-3 py-2 text-sm text-gray-100 focus:border-cyber-primary focus:outline-none transition-colors"
          />
        </div>
        <button
          @click="onSubmit"
          :disabled="!alertInput.trim()"
          class="px-5 py-2 bg-cyber-primary/20 border border-cyber-primary text-cyber-primary rounded font-bold text-sm hover:bg-cyber-primary/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all hover:glow-primary"
        >
          START
        </button>
      </div>
    </div>

    <!-- Log output -->
    <div class="flex-1 overflow-hidden">
      <slot name="log-panel"></slot>
    </div>
  </div>
</template>
