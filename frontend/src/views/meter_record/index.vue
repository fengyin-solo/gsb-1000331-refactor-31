<template>
  <section class="page" data-module="meter_record">
    <header class="page-head">
      <div>
        <h2>水表管理管理</h2>
        <p class="page-desc">维护贸易结算表，换表登记统一按旧表止度、新表起度、表号与安装位置规则判断。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记贸易结算表</button>
        <button class="btn" type="button" @click="exportRows">导出水表管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>换表判断</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">{{ replacementRule(row).status }}</button>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无水表管理数据，可先登记贸易结算表</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条水表管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detailRow" class="modal-mask" @click.self="closeDetail">
      <section class="modal-panel">
        <header class="modal-head">
          <h3>贸易结算表详情</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="column in detailFields" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ displayValue(detailRow, column) || '—' }}</dd>
          </template>
        </dl>
        <div class="rule-box">
          <strong>{{ replacementRule(detailRow).status }}</strong>
          <ul>
            <li v-for="issue in detailIssues(detailRow)" :key="issue" class="error-text">{{ issue }}</li>
            <li v-for="warning in replacementRule(detailRow).warnings" :key="warning" class="warning-text">{{ warning }}</li>
            <li v-if="!replacementRule(detailRow).issues.length && !replacementRule(detailRow).warnings.length">
              当前没有规则提示
            </li>
          </ul>
        </div>
      </section>
    </div>

    <div v-if="replacementTarget" class="modal-mask" @click.self="closeReplacementForm">
      <section class="modal-panel">
        <header class="modal-head">
          <h3>换表登记：{{ replacementTarget['表具编号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeReplacementForm">取消</button>
        </header>
        <form class="modal-form" @submit.prevent="submitReplacement">
          <label v-for="field in replacementFormFields" :key="field.name">
            <span>{{ field.label }}</span>
            <input v-model="replacementForm[field.name]" :placeholder="field.placeholder" />
          </label>
          <p v-if="formMessage" class="error-text">{{ formMessage }}</p>
          <div class="form-actions">
            <button class="btn primary" type="submit" :disabled="submitting">
              {{ submitting ? '提交中…' : '确认换表登记' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type JsonValue = string | number | null | boolean | JsonValue[] | { [key: string]: JsonValue }
type Row = Record<string, JsonValue>
type ReadingField = {
  raw: string
  value: string
  valid: boolean
  missing: boolean
  issue?: string
}
type TextField = ReadingField
type ReplacementRule = {
  status: string
  allowed: boolean
  issues: string[]
  missingFields?: string[]
  warnings: string[]
  fields: Record<string, TextField | ReadingField>
  hasReplacementInput: boolean
}
type ActionResponse = {
  ok: boolean
  message: string
  entry?: Row | null
}

const ENDPOINT = '/api/meter_record'
const columns = [
  '表具编号',
  '表具类型',
  '口径规格',
  '安装位置',
  '上次示数',
  '当前示数',
  '旧表止度',
  '新表起度',
  '新表表号',
  '抄表员',
  '表具状态',
]
const detailFields = ['旧表表号', '新表表号', '旧表安装位置', '新表安装位置', ...columns]
const actions = ['现场抄表', '换表登记', '恢复供电']
const replacementFormFields = [
  { name: '旧表表号', label: '旧表表号', placeholder: '默认取当前表具编号' },
  { name: '新表表号', label: '新表表号', placeholder: '请输入新表表号' },
  { name: '旧表止度', label: '旧表止度', placeholder: '如 123.40' },
  { name: '新表起度', label: '新表起度', placeholder: '新表通常为 0' },
  { name: '旧表安装位置', label: '旧表安装位置', placeholder: '默认取当前安装位置' },
  { name: '新表安装位置', label: '新表安装位置', placeholder: '必须与旧表位置一致' },
] as const

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const detailRow = ref<Row | null>(null)
const replacementTarget = ref<Row | null>(null)
const replacementForm = ref<Record<string, string>>({})
const formMessage = ref('')
const submitting = ref(false)

const stats = computed(() => [
  { label: '正常表具', value: rows.value.filter((row) => row.status === '正常').length },
  { label: '异常表具', value: rows.value.filter((row) => replacementRule(row).status === '历史异常').length },
  { label: '可换表具', value: rows.value.filter((row) => replacementRule(row).allowed).length },
])

function asRecord(value: JsonValue | undefined): Record<string, JsonValue> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, JsonValue>)
    : {}
}

function replacementRule(row: Row): ReplacementRule {
  const rule = asRecord(row['换表规则'])
  return {
    status: typeof rule.status === 'string' ? rule.status : '待补录',
    allowed: rule.allowed === true,
    issues: Array.isArray(rule.issues) ? rule.issues.filter((item): item is string => typeof item === 'string') : [],
    missingFields: Array.isArray(rule.missingFields)
      ? rule.missingFields.filter((item): item is string => typeof item === 'string')
      : [],
    warnings: Array.isArray(rule.warnings)
      ? rule.warnings.filter((item): item is string => typeof item === 'string')
      : [],
    fields: asRecord(rule.fields) as Record<string, ReadingField>,
    hasReplacementInput: rule.hasReplacementInput === true,
  }
}

function detailIssues(row: Row): string[] {
  const rule = replacementRule(row)
  const missing = (rule.missingFields ?? []).map((field) => `缺少${field}`)
  return [...rule.issues, ...missing]
}

function displayValue(row: Row, column: string): string {
  const value = row[column]
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '贸易结算表登记入口尚未接入审批流'
}

function openDetail(row: Row) {
  detailRow.value = row
}

function closeDetail() {
  detailRow.value = null
}

function closeReplacementForm() {
  if (submitting.value) return
  replacementTarget.value = null
  replacementForm.value = {}
  formMessage.value = ''
}

function runAction(action: string, row: Row) {
  if (action === '换表登记') {
    replacementTarget.value = row
    replacementForm.value = {
      旧表表号: String(row['表具编号'] ?? ''),
      新表表号: String(row['新表表号'] ?? ''),
      旧表止度: String(row['旧表止度'] ?? row['当前示数'] ?? ''),
      新表起度: String(row['新表起度'] ?? '0'),
      旧表安装位置: String(row['旧表安装位置'] ?? row['安装位置'] ?? ''),
      新表安装位置: String(row['新表安装位置'] ?? row['安装位置'] ?? ''),
    }
    formMessage.value = ''
    return
  }
  void submitAction(row.id, action, {})
}

async function submitReplacement() {
  if (!replacementTarget.value) return
  const values = Object.fromEntries(
    Object.entries(replacementForm.value).filter(([, value]) => value.trim() !== ''),
  )
  await submitAction(replacementTarget.value.id, '换表登记', values)
}

async function submitAction(rowId: JsonValue, action: string, values: Record<string, string>) {
  errorMessage.value = ''
  formMessage.value = ''
  submitting.value = true
  const isReplacementForm = action === '换表登记' && Boolean(replacementTarget.value)
  try {
    const response = await request(`${ENDPOINT}/${String(rowId)}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...values } }),
    })
    const payload = (await response.json()) as ActionResponse
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '水表管理动作未生效，请稍后重试')
    }
    replacementTarget.value = null
    replacementForm.value = {}
    await reload()
  } catch (error) {
    const message = error instanceof Error ? error.message : '水表管理操作失败'
    if (isReplacementForm) formMessage.value = message
    errorMessage.value = message
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('贸易结算表列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (detailRow.value) {
      detailRow.value = rows.value.find((row) => String(row.id) === String(detailRow.value?.id)) ?? null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '水表管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgb(15 23 42 / 45%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 20;
}

.modal-panel {
  width: min(760px, 100%);
  max-height: 86vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px;
  box-shadow: 0 18px 48px rgb(15 23 42 / 24%);
}

.modal-head,
.form-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.modal-head h3 {
  margin: 0;
}

.detail-grid {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 6px 10px;
  margin: 0 0 12px;
  font-size: 13px;
}

.detail-grid dt {
  color: var(--muted);
}

.detail-grid dd {
  margin: 0;
}

.rule-box {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: #f8fafc;
}

.rule-box ul {
  margin: 8px 0 0;
  padding-left: 18px;
}

.modal-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.modal-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--muted);
}

.modal-form input {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 9px;
  color: #1f2937;
}

.modal-form p,
.form-actions {
  grid-column: 1 / -1;
  margin: 0;
}

.warning-text {
  color: #b45309;
}
</style>
