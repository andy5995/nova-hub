<script setup lang="ts">
/**
 * Everything players send between planets other than individual attacks:
 * Terrorist Ops and their results, trade deals, spy reports, Spy Guys,
 * messages, and Gooie and Special Op traffic.
 *
 * Like Attacks, this says who sent what kind of thing to whom and how far it
 * got, never what was in it. An admin can reveal one event's contents by
 * clicking -- never by default, so an admin who plays does not see them by
 * accident -- and the server refuses everyone else. A message's text is never
 * revealed to anyone: only that it was sent, and to whom.
 */
import { computed, onMounted, ref, watch } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { leaguesApi, trafficApi, type TrafficDetails, type TrafficEvent } from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const loading = ref(false)
const error = ref<string | null>(null)
const events = ref<TrafficEvent[]>([])
const leagues = ref<Array<{ id: number; name: string }>>([])
const expanded = ref<Set<string>>(new Set())

const days = ref(14)
const leagueId = ref<number | undefined>(undefined)
const planet = ref<number | undefined>(undefined)
const kind = ref('')

async function load() {
  loading.value = true
  error.value = null
  try {
    const { data } = await trafficApi.list({
      days: days.value,
      league_id: leagueId.value,
      planet: planet.value || undefined,
    })
    events.value = data
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not load traffic'
  } finally {
    loading.value = false
  }
}

const kinds = computed(() => [...new Set(events.value.map(e => e.kind))].sort())
const shown = computed(() => events.value.filter(e => !kind.value || e.kind === kind.value))
const byKey = computed(() => new Map(events.value.map(e => [e.key, e])))

function toggle(key: string) {
  const next = new Set(expanded.value)
  next.has(key) ? next.delete(key) : next.add(key)
  expanded.value = next
}

function when(stamp: string | null): string {
  if (!stamp) return '-'
  return stamp.replace('T', ' ').slice(0, 19)
}

function route(e: TrafficEvent): string {
  const from = `${e.from_planet}${e.from_letter ?? ''}`
  if (e.recipients === 'all planets') return `${from} → all planets`
  if (e.recipients !== null) {
    return e.recipients.length > 1
      ? `${from} → ${e.to_planet} (${e.recipients.split('').join(', ')})`
      : `${from} → ${e.to_planet}${e.recipients}`
  }
  return `${from} → ${e.to_planet}${e.to_letter ?? ''}`
}

function pairText(e: TrafficEvent): string {
  if (!e.paired_with) return ''
  const other = byKey.value.get(e.paired_with)
  const where = other ? (other.delivered ? 'delivered' : other.stage) : 'outside this window'
  return e.kind === 'Terrorist Result' ? `answers an op (${where})` : `result ${where}`
}

// Admin reveal: fetched only on click, forgotten when hidden.
const details = ref<Record<string, TrafficDetails>>({})
const detailsLoading = ref<string | null>(null)
const detailsError = ref<Record<string, string>>({})

async function reveal(key: string) {
  detailsLoading.value = key
  const errs = { ...detailsError.value }
  delete errs[key]
  try {
    const { data } = await trafficApi.details(key)
    details.value = { ...details.value, [key]: data }
  } catch (e: any) {
    errs[key] = e?.response?.data?.detail || 'Could not reveal this'
  } finally {
    detailsError.value = errs
    detailsLoading.value = null
  }
}

function hide(key: string) {
  const next = { ...details.value }
  delete next[key]
  details.value = next
}

function label(k: string): string {
  return k.replace(/_/g, ' ')
}

onMounted(async () => {
  try {
    const { data } = await leaguesApi.list()
    leagues.value = data
  } catch {
    // The league filter is a convenience; the page works without it.
  }
  await load()
})

watch([days, leagueId, planet], load)
</script>

<template>
  <AppLayout>
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Traffic</h1>
          <p class="text-muted">
            BRE ops, trade deals, spy reports and messages between planets &mdash; who to whom, not what
          </p>
        </div>
        <div class="window-picker">
          <label for="days">Reached hub</label>
          <select id="days" v-model.number="days" class="form-select">
            <option :value="1">Last 24 hours</option>
            <option :value="7">Last 7 days</option>
            <option :value="14">Last 14 days</option>
            <option :value="30">Last 30 days</option>
            <option :value="90">Last 90 days</option>
          </select>
        </div>
      </header>

      <div v-if="error" class="alert alert-error">
        {{ error }}
        <button class="btn btn-sm btn-secondary mt-2" @click="load">Retry</button>
      </div>

      <div v-else-if="loading && events.length === 0" class="loading-state">
        <div class="spinner"></div>
        <p>Loading traffic...</p>
      </div>

      <div v-else class="card">
        <div class="card-header filter-bar">
          <h2>{{ shown.length }} event<span v-if="shown.length !== 1">s</span></h2>
          <div class="filters">
            <select v-model="leagueId" class="form-select">
              <option :value="undefined">All leagues</option>
              <option v-for="l in leagues" :key="l.id" :value="l.id">{{ l.name }}</option>
            </select>
            <select v-model="kind" class="form-select">
              <option value="">All kinds</option>
              <option v-for="k in kinds" :key="k" :value="k">{{ k }}</option>
            </select>
            <input v-model.number="planet" type="number" min="1" class="form-input narrow"
                   placeholder="Planet" title="Either end" />
          </div>
        </div>
        <div class="card-body" style="padding: 0;">
          <div v-if="shown.length === 0" class="empty">
            <p class="text-muted">
              Nothing matches. Traffic is read from BRE packets as they reach the hub;
              packets stored earlier appear once <code>backfill_attacks.py --redo</code> has been run.
            </p>
          </div>
          <table v-else class="table">
            <thead>
              <tr>
                <th>Reached hub</th>
                <th>League</th>
                <th>Kind</th>
                <th>From &rarr; to</th>
                <th>Where it is</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="e in shown" :key="e.key">
                <tr class="clickable" @click="toggle(e.key)">
                  <td class="font-mono">{{ when(e.at_hub) }}</td>
                  <td>{{ e.league_name || '-' }}</td>
                  <td>{{ e.kind }}</td>
                  <td class="font-mono">{{ route(e) }}</td>
                  <td>
                    <span class="badge" :class="e.stage === 'delivered' ? 'badge-success' : 'badge-warning'">
                      {{ e.stage }}
                    </span>
                    <div v-if="e.paired_with" class="text-muted small">{{ pairText(e) }}</div>
                  </td>
                </tr>
                <tr v-if="expanded.has(e.key)" class="detail">
                  <td colspan="5">
                    <div class="detail-grid">
                      <div>
                        <h3>Packets that carried it</h3>
                        <table class="table compact">
                          <thead>
                            <tr><th>Packet</th><th>Boards</th><th>At hub</th><th>Taken</th></tr>
                          </thead>
                          <tbody>
                            <tr v-for="h in e.hops" :key="h.packet_id">
                              <td class="font-mono">{{ h.filename }}</td>
                              <td class="font-mono">{{ h.source_bbs }} &rarr; {{ h.dest_bbs }}</td>
                              <td class="font-mono">{{ when(h.at_hub) }}</td>
                              <td class="font-mono">{{ h.taken ? when(h.taken) : 'not yet' }}</td>
                            </tr>
                          </tbody>
                        </table>
                        <p v-if="e.stamp" class="text-muted small">
                          Resolved {{ when(e.stamp) }} on the far side's clock.
                        </p>
                      </div>
                      <div>
                        <template v-if="e.kind === 'Message'">
                          <p class="text-muted small">Message contents are never shown.</p>
                        </template>
                        <template v-else-if="authStore.isAdmin && e.revealable">
                          <template v-if="details[e.key]">
                            <h3>
                              Contents
                              <button class="btn btn-sm btn-secondary" @click="hide(e.key)">Hide</button>
                            </h3>
                            <dl>
                              <template v-for="(v, k) in details[e.key].details" :key="k">
                                <dt>{{ label(String(k)) }}</dt>
                                <dd v-if="typeof v === 'object'" class="font-mono">
                                  <span v-for="(n, g) in v" :key="g">{{ n }} {{ g }}&nbsp; </span>
                                </dd>
                                <dd v-else class="font-mono">{{ v }}</dd>
                              </template>
                            </dl>
                          </template>
                          <template v-else>
                            <button class="btn btn-sm btn-secondary" :disabled="detailsLoading === e.key"
                                    @click="reveal(e.key)">
                              {{ detailsLoading === e.key ? 'Revealing…' : 'Reveal contents (admin)' }}
                            </button>
                            <span class="text-muted small"> hidden game state &mdash; each reveal is logged</span>
                            <div v-if="detailsError[e.key]" class="text-danger small">{{ detailsError[e.key] }}</div>
                          </template>
                        </template>
                        <p v-else-if="authStore.isAdmin" class="text-muted small">
                          This kind of record is not decoded yet.
                        </p>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
.page {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  gap: 1rem;
}

.page-header h1 {
  margin-bottom: 0.25rem;
}

.window-picker {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 4rem;
  gap: 1rem;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.filters {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.narrow {
  width: 6rem;
}

.empty {
  padding: 2rem;
  text-align: center;
}

.clickable {
  cursor: pointer;
}

.clickable:hover {
  background: var(--color-background-mute, rgba(127, 127, 127, 0.12));
}

.detail > td {
  background: var(--color-background-mute, rgba(127, 127, 127, 0.06));
  padding: 1rem 1.25rem;
}

.detail-grid {
  display: grid;
  grid-template-columns: 2fr minmax(18rem, 1fr);
  gap: 1.5rem;
}

.detail h3 {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
}

.detail dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.25rem 0.75rem;
  font-size: 0.85rem;
}

.detail dt {
  color: var(--color-text-muted);
}

.table.compact td,
.table.compact th {
  padding: 0.3rem 0.4rem;
  font-size: 0.85rem;
}
</style>
