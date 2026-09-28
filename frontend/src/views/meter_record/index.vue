<template>
  <section class="page" data-module="meter_record">
    <header class="page-head">
      <div>
        <h2>水表管理管理</h2>
        <p class="page-desc">维护贸易结算表，围绕表具编号、表具类型、口径规格、安装位置做登记、筛选与状态流转。</p>
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
          <th v-for="column in tableColumns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in tableColumns" :key="column">
            <button v-if="column === replacementRuleColumn" class="link" type="button" @click="openDetail(row)">
              {{ formatRule(row[column]) }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">明细</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="handleAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="tableColumns.length + 1" class="empty-state">暂无水表管理数据，可先登记贸易结算表</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条水表管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="dialogVisible" class="modal-mask" @click.self="closeDialog">
      <div class="modal-card">
        <header class="modal-head">
          <strong>{{ dialogTitle }}</strong>
          <button class="link" type="button" @click="closeDialog">关闭</button>
        </header>

        <div v-if="dialogMode === 'detail'" class="modal-body">
          <p v-if="!detailRule" class="empty-state">该记录尚未填写换表信息。</p>
          <template v-else>
            <p :class="detailRule.valid ? 'valid-text' : 'error-text'">{{ detailRule.message }}</p>
            <dl class="rule-list">
              <template v-for="issue in detailRule.issues" :key="`${issue.field}-${issue.code}`">
                <dt>{{ issue.field }}</dt>
                <dd>{{ issue.message }}</dd>
              </template>
            </dl>
          </template>
        </div>

        <form v-else class="modal-body replacement-form" @submit.prevent="submitReplacement">
          <label v-for="field in replacementFields" :key="field">
            <span>{{ field }}</span>
            <input v-model="replacementForm[field]" :placeholder="`请输入${field}`" />
          </label>
          <p v-if="dialogMessage" :class="dialogValid ? 'valid-text' : 'error-text'">{{ dialogMessage }}</p>
          <footer class="modal-actions">
            <button class="btn" type="button" @click="checkReplacement">仅校验</button>
            <button class="btn primary" type="submit">确认登记</button>
          </footer>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type ReplacementIssue = {
  field: string
  code: string
  message: string
}

type ReplacementRule = {
  valid: boolean
  message: string
  issues: ReplacementIssue[]
  readings: Record<string, number>
}

type Row = Record<string, string | number | boolean | null | ReplacementRule | undefined> & {
  id: number
}

type ActionResponse = {
  ok: boolean
  message: string
  entry?: Row
}

const ENDPOINT = '/api/meter_record'
const columns = ["表具编号", "表具类型", "口径规格", "安装位置", "上次示数", "当前示数", "抄表员", "表具状态"]
const ruleColumns = ["换表规则"]
const tableColumns = computed(() => [...columns, ...ruleColumns])
const actions = ["现场抄表", "换表登记", "恢复供电"]
const replacementRuleColumn = '换表规则'
const replacementFields = ["旧表表号", "旧表止度", "新表表号", "新表起度", "新表安装位置"]
const statuses = ["正常", "待换表", "停走", "倒转", "缺电"]
const stats = [{"label": "正常表具", "value": 0}, {"label": "异常表具", "value": 0}, {"label": "待换表具", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const dialogVisible = ref(false)
const dialogMode = ref<'detail' | 'replace'>('detail')
const activeRow = ref<Row | null>(null)
const detailRule = ref<ReplacementRule | null>(null)
const dialogMessage = ref('')
const dialogValid = ref(false)
const replacementForm = ref<Record<string, string>>({})

const dialogTitle = ref('换表明细')

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

function formatRule(value: Row[keyof Row]): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return '未校验'
  }
  const rule = value as ReplacementRule
  return rule.valid ? '通过' : `${rule.issues.length}项问题`
}

function closeDialog() {
  dialogVisible.value = false
  activeRow.value = null
  detailRule.value = null
  dialogMessage.value = ''
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('贸易结算表明细读取失败')
    }
    const entry = (await response.json()) as Row
    const rule = entry[replacementRuleColumn]
    activeRow.value = entry
    detailRule.value = rule && typeof rule === 'object' && !Array.isArray(rule)
      ? rule as ReplacementRule
      : null
    dialogMode.value = 'detail'
    dialogTitle.value = `换表明细（${entry.id}）`
    dialogVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '贸易结算表明细读取失败'
  }
}

function handleAction(action: string, row: Row) {
  if (action === '换表登记') {
    openReplacement(row)
    return
  }
  void runSimpleAction(action, row)
}

function openReplacement(row: Row) {
  activeRow.value = row
  dialogMode.value = 'replace'
  dialogTitle.value = `换表登记（${row.id}）`
  dialogMessage.value = ''
  replacementForm.value = Object.fromEntries(replacementFields.map((field) => [
    field,
    typeof row[field] === 'string' || typeof row[field] === 'number' ? String(row[field]) : '',
  ]))
  dialogVisible.value = true
}

async function readActionResponse(response: Response): Promise<ActionResponse> {
  const payload = await response.json() as ActionResponse
  if (!response.ok) {
    throw new Error(payload.message || '水表管理动作未生效，请稍后重试')
  }
  return payload
}

async function runSimpleAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await readActionResponse(response)
    if (!payload.ok) {
      throw new Error(payload.message)
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '水表管理操作失败'
  }
}

async function postReplacement(values: Record<string, string>, action?: string): Promise<ActionResponse> {
  const response = await request(
    action ? `${ENDPOINT}/${activeRow.value?.id}/actions` : `${ENDPOINT}/${activeRow.value?.id}/replacement/check`,
    {
      method: 'POST',
      body: JSON.stringify({ values: action ? { ...values, action } : values }),
    },
  )
  return readActionResponse(response)
}

async function checkReplacement() {
  if (!activeRow.value) return
  try {
    const payload = await postReplacement(replacementForm.value)
    const rule = payload.entry?.[replacementRuleColumn]
    detailRule.value = rule && typeof rule === 'object' && !Array.isArray(rule)
      ? rule as ReplacementRule
      : null
    dialogMessage.value = payload.message
    dialogValid.value = payload.ok
  } catch (error) {
    dialogMessage.value = error instanceof Error ? error.message : '换表校验失败'
    dialogValid.value = false
  }
}

async function submitReplacement() {
  if (!activeRow.value) return
  try {
    const payload = await postReplacement(replacementForm.value, '换表登记')
    if (!payload.ok) {
      dialogValid.value = false
      dialogMessage.value = payload.message
      return
    }
    closeDialog()
    await reload()
  } catch (error) {
    dialogMessage.value = error instanceof Error ? error.message : '换表登记失败'
    dialogValid.value = false
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
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
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
}

.modal-card {
  width: min(560px, calc(100vw - 32px));
  background: #fff;
  border-radius: 8px;
  border: 1px solid var(--border);
  padding: 14px 16px;
}

.modal-head,
.modal-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.modal-body {
  margin-top: 12px;
}

.replacement-form {
  display: grid;
  gap: 10px;
}

.replacement-form label span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}

.replacement-form input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}

.rule-list {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 6px 10px;
  margin: 8px 0 0;
}

.rule-list dt {
  color: var(--muted);
}

.rule-list dd {
  margin: 0;
}

.valid-text {
  color: #067647;
}
</style>
