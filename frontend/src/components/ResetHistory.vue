<script setup lang="ts">
// Every reset of a league, newest first. Each row opens into what it changed
// from the reset before it. Resets only seen in a Game Start packet (BRE)
// carry the three settings the hub decodes so far.
import { onMounted, ref, watch } from 'vue'
import {
  apiError,
  gameResetApi,
  type ResetField,
  type ResetSummary,
  type ResetValue
} from '@/services/api'

const props = defineProps<{ leagueId: number; fields: ResetField[]; refreshKey: number }>()
const emit = defineEmits<{ open: [resetId: number] }>()

const rows = ref<ResetSummary[]>([])
const loading = ref(true)
const error = ref('')
const expanded = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    rows.value = (await gameResetApi.history(props.leagueId)).data
    error.value = ''
  } catch (e) {
    error.value = apiError(e, 'Could not load the reset history')
  } finally {
    loading.value = false
  }
}

function display(f: ResetField, v: ResetValue | undefined): string {
  if (v === null || v === undefined || v === '') return f.kind === 'date' ? 'day of reset' : '—'
  if (f.kind === 'toggle') return v ? 'Enabled' : 'Disabled'
  if (f.kind === 'choice') return f.choices.find((c) => c.letter === v)?.name ?? String(v)
  if (f.kind === 'number') return Number(v).toLocaleString()
  return String(v)
}

// Against the applied reset before it; the first one ever has nothing to
// compare with, so it lists what it set.
function diff(i: number) {
  const row = rows.value[i]
  const before = rows.value.slice(i + 1).find((r) => r.status === 'applied')
  return props.fields
    .filter((f) => f.id in row.settings)
    .filter((f) => !before || !(f.id in before.settings) || before.settings[f.id] !== row.settings[f.id])
    .map((f) => ({
      label: f.label,
      from: before && f.id in before.settings ? display(f, before.settings[f.id]) : '',
      to: display(f, row.settings[f.id])
    }))
}

function when(iso: string | null): string {
  return iso ? iso.replace('T', ' ').slice(0, 16) : ''
}

watch(() => props.refreshKey, load)
onMounted(load)
</script>

<template>
  <section class="card mb-4">
    <div class="card-header">
      <h3>Reset history</h3>
    </div>
    <div class="card-body history">
      <div v-if="error" class="alert alert-error">{{ error }}</div>
      <p v-else-if="loading" class="text-muted">Loading...</p>
      <p v-else-if="!rows.length" class="text-muted">
        No resets yet: none from the console, and no Game Start in the packets the hub holds.
      </p>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Game start</th>
            <th>Ended</th>
            <th>By</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(r, i) in rows" :key="r.id">
            <tr class="row" @click="expanded = expanded === r.id ? null : r.id">
              <td>{{ when(r.game_start) || `performed ${when(r.applied_at)}` }}</td>
              <td>
                <span v-if="r.status !== 'applied'" class="text-muted">—</span>
                <span v-else-if="r.ended">{{ when(r.ended) }}</span>
                <span v-else class="badge badge-info">current</span>
              </td>
              <td>
                <template v-if="r.source === 'observed'">
                  <span class="text-muted" title="Seen in a Game Start packet, not performed from the console">
                    seen in packets
                  </span>
                </template>
                <template v-else>{{ r.applied_by }}</template>
              </td>
              <td>
                <span v-if="r.status === 'applying'" class="badge badge-info">under way</span>
                <span v-else-if="r.status === 'failed'" class="badge badge-danger">failed</span>
                <span v-else-if="r.confirmed === false" class="badge badge-danger">Game Start disagrees</span>
                <span v-else-if="r.confirmed" class="badge badge-success">confirmed</span>
                <span v-else-if="r.source === 'console'" class="badge badge-warning">awaiting Game Start</span>
                <span v-else class="badge badge-success">applied</span>
              </td>
              <td class="toggle">{{ expanded === r.id ? '▾' : '▸' }}</td>
            </tr>
            <tr v-if="expanded === r.id" class="detail">
              <td colspan="5">
                <p v-if="r.error" class="alert alert-error">{{ r.error }}</p>
                <p v-if="r.notes" class="notes">{{ r.notes }}</p>
                <table class="table diff">
                  <thead>
                    <tr><th>Setting</th><th>Before</th><th>This reset</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="d in diff(i)" :key="d.label">
                      <td>{{ d.label }}</td>
                      <td class="text-muted">{{ d.from }}</td>
                      <td><strong>{{ d.to }}</strong></td>
                    </tr>
                    <tr v-if="!diff(i).length">
                      <td colspan="3" class="text-muted">The same settings as the reset before.</td>
                    </tr>
                  </tbody>
                </table>
                <button v-if="r.source === 'console'" class="btn btn-secondary btn-sm" @click.stop="emit('open', r.id)">
                  Progress and editor log
                </button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.history {
  overflow-x: auto;
}

.row {
  cursor: pointer;
}

.toggle {
  width: 1.5rem;
  color: var(--color-text-muted);
}

.detail > td {
  background: var(--color-bg);
}

.diff td,
.diff th {
  font-size: 0.85rem;
}

.notes {
  white-space: pre-wrap;
  font-size: 0.875rem;
}
</style>
