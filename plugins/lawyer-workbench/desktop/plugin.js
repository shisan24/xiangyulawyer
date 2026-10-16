// © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
/**
 * Lawyer Workbench — Hermes desktop plugin (gateway-native).
 * 案件办理只读工作台：确认事项、会话工作线索（可归并/忽略）、Kanban 状态。
 *
 * 后端：plugins/lawyer-workbench/dashboard/plugin_api.py
 *（gateway 挂载到 /api/plugins/lawyer-workbench/，由 ctx.rest 调用）
 * 归并动作写入该插件自己的 session-merge.json（不动案件目录 / Kanban）。
 */
import { cn, host, Tip, useQuery } from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

const ID = 'lawyer-workbench'
let rest = null // ctx.rest bound in register()

const CATEGORY_ORDER = ['诉讼案件', '常法事项', '专项非诉', '内部管理']
const CATEGORY_DOTS = {
  诉讼案件: 'bg-(--ui-accent)',
  常法事项: 'bg-(--ui-green)',
  专项非诉: 'bg-(--ui-orange)',
  内部管理: 'bg-(--ui-text-tertiary)'
}

function statusTone(status) {
  const s = String(status || '')
  if (s.includes('待补') || s.includes('已阻塞')) return 'text-(--ui-danger)'
  if (s.includes('待核') || s.includes('待复核') || s.includes('待推进')) return 'text-(--ui-orange)'
  if (s.includes('已交付') || s.includes('已结案')) return 'text-(--ui-green)'
  return 'text-(--ui-text-tertiary)'
}

function Chip({ onClick, active, children }) {
  return jsx('button', {
    type: 'button',
    onClick,
    className: cn(
      'rounded-full border px-2 py-0.5 text-[0.6875rem] transition-colors',
      active
        ? 'border-(--ui-accent) bg-(--ui-accent)/15 text-(--ui-accent)'
        : 'border-(--ui-stroke-secondary) text-(--ui-text-secondary) hover:border-(--ui-text-tertiary)'
    ),
    children
  })
}

function Stat({ label, value, note, tone }) {
  return jsxs('div', {
    className: 'flex flex-col gap-0.5 rounded-lg border border-(--ui-stroke-secondary) px-2.5 py-2',
    children: [
      jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: label }),
      jsxs('div', {
        className: 'flex items-baseline gap-1.5',
        children: [
          jsx('span', { className: cn('text-lg font-semibold', tone || 'text-foreground'), children: value }),
          note ? jsx('span', { className: 'truncate text-[0.625rem] text-(--ui-text-tertiary)', children: note }) : null
        ]
      })
    ]
  })
}

function ActivityTag({ children }) {
  return jsx('span', {
    className: 'rounded bg-(--ui-bg-tertiary) px-1 py-px text-[0.625rem] text-(--ui-text-secondary)',
    children
  })
}

function TargetSelect({ matters, value, onChange, placeholder }) {
  return jsx('select', {
    value: value || '',
    onChange: e => onChange(e.target.value),
    className:
      'w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-1.5 py-1 text-[0.6875rem] text-(--ui-text-secondary) outline-none focus:border-(--ui-accent)',
    children: [
      jsx('option', { key: '', value: '', children: placeholder || '选择归并目标事项' }),
      ...matters.map(m => jsx('option', {
        key: m.id || m.name,
        value: m.id || m.name,
        children: `${m.category || ''} · ${m.name || m.id}`
      }))
    ]
  })
}

function ActionBtn({ tone, onClick, disabled, children }) {
  const base = 'rounded px-1.5 py-0.5 text-[0.6875rem] transition-colors disabled:opacity-40'
  const toneCls = {
    primary: 'bg-(--ui-accent)/15 text-(--ui-accent) hover:bg-(--ui-accent)/25',
    danger: 'bg-(--ui-danger)/10 text-(--ui-danger) hover:bg-(--ui-danger)/20',
    ghost: 'text-(--ui-text-tertiary) hover:bg-(--ui-bg-tertiary)'
  }
  return jsx('button', {
    type: 'button',
    onClick,
    disabled,
    className: cn(base, toneCls[tone] || toneCls.ghost),
    children
  })
}

function PendingSessionCard({ s, matters, onMerge, onIgnore }) {
  const acts = Array.isArray(s.activities) ? s.activities : []
  const sug = s.suggested_target
  const defaultTarget = sug ? (sug.matter_id || sug.matter_name) : ''
  const [target, setTarget] = useState(defaultTarget)
  return jsxs('div', {
    className: 'flex flex-col gap-1.5 rounded-lg border border-(--ui-stroke-secondary)/70 px-2.5 py-2',
    children: [
      jsxs('div', {
        className: 'flex items-start justify-between gap-2',
        children: [
          jsx('div', { className: 'min-w-0 flex-1 truncate text-xs font-medium', title: s.title, children: s.title || '未命名线索' }),
          jsxs('div', {
            className: 'flex flex-wrap items-center gap-1 text-[0.625rem] text-(--ui-text-tertiary)',
            children: [
              jsx('span', { children: s.category || '未分类' }),
              s.litigation_type ? jsx('span', { children: `· ${s.litigation_type}` }) : null,
              jsx('span', { children: `· ${s.session_count || 1} 会话` })
            ]
          })
        ]
      }),
      acts.length
        ? jsx('div', { className: 'flex flex-wrap gap-1', children: acts.slice(0, 4).map(a => jsx(ActivityTag, { key: a, children: a })) })
        : null,
      s.summary
        ? jsx('div', {
            className: 'line-clamp-2 text-[0.6875rem] leading-snug text-(--ui-text-tertiary)',
            title: s.summary,
            children: s.summary
          })
        : null,
      sug
        ? jsx('div', {
            className: 'text-[0.625rem] text-(--ui-accent)',
            children: `推荐归并到：${sug.matter_name}（相似度 ${Math.round((sug.score || 0) * 100)}%）`
          })
        : jsx('div', { className: 'text-[0.625rem] text-(--ui-text-tertiary)', children: '暂无相似事项推荐，请手动选择目标。' }),
      jsxs('div', {
        className: 'flex flex-col gap-1.5',
        children: [
          jsx(TargetSelect, {
            key: 'target',
            matters,
            value: target,
            onChange: setTarget,
            placeholder: sug ? '使用推荐目标' : '选择归并目标事项'
          }),
          jsxs('div', {
            key: 'actions',
            className: 'flex items-center gap-1',
            children: [
              jsx(ActionBtn, {
                tone: 'primary',
                disabled: !target,
                onClick: () => {
                  const tm = matters.find(m => (m.id || m.name) === target)
                  onMerge(s, tm)
                },
                children: '归并'
              }),
              jsx(ActionBtn, { tone: 'danger', onClick: () => onIgnore(s), children: '忽略' }),
              jsx('span', { className: 'ml-auto text-[0.625rem] text-(--ui-text-tertiary)', children: s.id })
            ]
          })
        ]
      })
    ]
  })
}

function MergedSessionCard({ s, onUndo }) {
  const st = s.merge_state === 'merged' ? '已归并' : '已忽略'
  const tone = s.merge_state === 'merged' ? 'text-(--ui-green)' : 'text-(--ui-text-tertiary)'
  return jsxs('div', {
    className: 'flex flex-col gap-1 rounded-lg border border-(--ui-stroke-secondary)/50 px-2.5 py-1.5 opacity-70',
    children: [
      jsxs('div', {
        className: 'flex items-start justify-between gap-2',
        children: [
          jsx('div', { className: 'min-w-0 flex-1 truncate text-xs text-(--ui-text-secondary)', children: s.title || '未命名线索' }),
          jsx('span', { className: cn('shrink-0 text-[0.625rem]', tone), children: st })
        ]
      }),
      s.merged_into
        ? jsx('div', { className: 'truncate text-[0.6875rem] text-(--ui-text-tertiary)', children: `→ ${s.merged_into.name || s.merged_into}` })
        : null,
      jsx('div', {
        className: 'flex justify-end',
        children: jsx(ActionBtn, { tone: 'ghost', onClick: () => onUndo(s), children: '撤销' })
      })
    ]
  })
}

function MatterCard({ m, onToggle, expanded }) {
  const cat = m.category || m.mode || '未分类'
  const proc = m.litigation_type || ''
  const acts = Array.isArray(m.activities) ? m.activities : []
  const todos = Array.isArray(m.todo_items) ? m.todo_items.filter(t => t.state !== 'done') : []
  return jsxs('div', {
    className: 'flex flex-col gap-1 rounded-lg border border-(--ui-stroke-secondary) px-2.5 py-2',
    children: [
      jsxs('button', {
        type: 'button',
        onClick: onToggle,
        className: 'flex w-full items-start justify-between gap-2 text-left',
        children: [
          jsx('div', { className: 'min-w-0 flex-1 text-xs font-medium leading-snug', children: m.name || m.id || '未命名事项' }),
          jsxs('span', {
            className: 'flex shrink-0 items-center gap-1 text-[0.6875rem]',
            children: [
              jsx('span', { className: cn(statusTone(m.status || m.stage)) , children: m.status || m.stage || '待登记' }),
              jsx('span', { className: 'text-(--ui-text-tertiary)', children: expanded ? '▴' : '▾' })
            ]
          })
        ]
      }),
      jsxs('div', {
        className: 'flex flex-wrap items-center gap-1',
        children: [
          jsxs('span', {
            className: 'inline-flex items-center gap-1 text-[0.6875rem] text-(--ui-text-secondary)',
            children: [
              jsx('span', { className: cn('inline-block h-1.5 w-1.5 rounded-full', CATEGORY_DOTS[cat] || 'bg-(--ui-text-tertiary)') }),
              jsx('span', { children: cat })
            ]
          }),
          proc ? jsx('span', { className: 'text-[0.625rem] text-(--ui-text-tertiary)', children: `· ${proc}` }) : null,
          ...acts.slice(0, 4).map(a => jsx(ActivityTag, { key: a, children: a }))
        ]
      }),
      expanded
        ? jsxs('div', {
            className: 'flex flex-col gap-1 border-t border-(--ui-stroke-secondary)/60 pt-1.5 text-[0.6875rem]',
            children: [
              m.next_action && !/待确认/.test(String(m.next_action))
                ? jsx('div', { className: 'text-(--ui-text-secondary)', children: `后续：${m.next_action}` })
                : null,
              m.open_issues > 0
                ? jsx('div', { className: 'text-(--ui-orange)', children: `待办 ${m.open_issues} 项` })
                : null,
              todos.slice(0, 5).map((t, i) =>
                jsx('div', { key: `${t.text}-${i}`, className: 'flex items-start gap-1 text-(--ui-text-tertiary)', children: [`· ${t.text}`] })
              ),
              m.path
                ? jsx('div', { className: 'truncate text-(--ui-text-tertiary)', title: m.path, children: `目录：${m.path}` })
                : null
            ]
          })
        : null
    ]
  })
}

function WorkbenchPane() {
  const [filter, setFilter] = useState('all')
  const [expandedId, setExpandedId] = useState(null)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: [ID, 'workbench'],
    queryFn: () => rest('/workbench'),
    refetchInterval: 30000,
    retry: 1
  })

  const runMerge = async (key, action, target) => {
    try {
      const j = await rest('/merge', { method: 'POST', body: { key, action, target_matter: target } })
      if (!j.ok) host.notify({ kind: 'warning', message: j.error || '归并操作失败' })
      refetch()
    } catch (e) {
      host.notify({ kind: 'warning', message: `归并操作失败：${e && e.message || e}` })
    }
  }

  const matters = Array.isArray(data?.matters) ? data.matters : []
  const sessions = data?.session_work?.items || []
  const counts = data?.kanban?.counts || {}
  const kanbanTotal = Object.values(counts).reduce((a, b) => a + (Number(b) || 0), 0)
  const sessionCount = data?.session_work?.count ?? sessions.length
  const openIssues = matters.reduce((sum, m) => sum + (Number(m.open_issues) || 0), 0)

  const pending = sessions.filter(s => !s.merge_state || s.merge_state === '')
  const processed = sessions.filter(s => s.merge_state === 'merged' || s.merge_state === 'ignored')

  const shown = filter === 'all'
    ? matters
    : matters.filter(m => (m.category || m.mode || '未分类') === filter)

  const catCounts = {}
  matters.forEach(m => {
    const c = m.category || m.mode || '未分类'
    catCounts[c] = (catCounts[c] || 0) + 1
  })

  const doMerge = (s, tm) => {
    const targetPayload = tm
      ? { id: tm.id || tm.name, name: tm.name || tm.id, category: tm.category || '' }
      : null
    runMerge(s.id, 'merged', targetPayload)
  }
  const doIgnore = s => runMerge(s.id, 'ignored', null)
  const doUndo = s => runMerge(s.id, 'unmerged', null)

  return jsxs('div', {
    className: 'flex h-full flex-col gap-2.5 overflow-y-auto p-3 text-sm',
    children: [
      jsxs('div', {
        className: 'flex items-center justify-between gap-2',
        children: [
          jsx('div', { className: 'text-xs font-semibold uppercase tracking-wide text-(--ui-text-tertiary)', children: '律师工作台' }),
          jsx('button', {
            type: 'button',
            onClick: () => refetch(),
            className: 'text-[0.6875rem] text-(--ui-text-tertiary) transition-colors hover:text-(--ui-accent)',
            children: '刷新'
          })
        ]
      }),

      isLoading
        ? jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: '读取中…' })
        : isError
          ? jsxs('div', {
              className: 'flex flex-col gap-1.5 rounded-lg border border-(--ui-danger)/40 px-2.5 py-2',
              children: [
                jsx('div', { className: 'text-xs text-(--ui-danger)', children: '后端数据读取失败' }),
                jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: '检查 gateway 插件 lawy…workbench 是否已启用并重启。' })
              ]
            })
          : jsxs(Fragment, {
              children: [
                data?.warnings?.length
                  ? jsx('div', { className: 'text-[0.6875rem] text-(--ui-orange)', children: `另有 ${data.warnings.length} 项读取/范围警告` })
                  : null,
                jsxs('div', {
                  className: 'grid grid-cols-2 gap-1.5',
                  children: [
                    jsx(Stat, { label: '已确认事项', value: matters.length, note: '案件进度索引' }),
                    jsx(Stat, { label: '待归并线索', value: pending.length, note: `已处理 ${processed.length}`, tone: 'text-(--ui-orange)' }),
                    jsx(Stat, { label: '前次未完成', value: openIssues, note: '待办合计' }),
                    jsx(Stat, { label: 'Kanban 任务', value: kanbanTotal, note: '只读' })
                  ]
                }),
                jsxs('div', {
                  className: 'flex flex-wrap gap-1',
                  children: [
                    jsx(Chip, { active: filter === 'all', onClick: () => setFilter('all'), children: '全部' }),
                    ...CATEGORY_ORDER
                      .filter(c => catCounts[c])
                      .map(c => jsx(Chip, {
                        key: c,
                        active: filter === c,
                        onClick: () => setFilter(c),
                        children: `${c} ${catCounts[c]}`
                      }))
                  ]
                })
              ]
            }),

      jsx('div', { className: 'border-t border-(--ui-stroke-secondary) pt-2 text-xs font-semibold uppercase tracking-wide text-(--ui-text-tertiary)', children: '已确认事项' }),
      !isLoading && !isError && shown.length === 0
        ? jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: '该分类暂无已确认事项。' })
        : shown.slice(0, 8).map(m => jsx(MatterCard, {
            key: m.id || m.name,
            m,
            expanded: expandedId === (m.id || m.name),
            onToggle: () => setExpandedId(expandedId === (m.id || m.name) ? null : (m.id || m.name))
          })),

      jsx('div', { className: 'border-t border-(--ui-stroke-secondary) pt-2 text-xs font-semibold uppercase tracking-wide text-(--ui-text-tertiary)', children: '会话工作线索（待归并）' }),
      !isLoading && !isError && pending.length === 0
        ? jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: '没有待归并的线索。' })
        : pending.slice(0, 5).map(s => jsx(PendingSessionCard, {
            key: s.id || s.title,
            s,
            matters,
            onMerge: doMerge,
            onIgnore: doIgnore
          })),

      processed.length > 0
        ? jsxs(Fragment, {
            children: [
              jsx('div', { className: 'border-t border-(--ui-stroke-secondary) pt-2 text-xs font-semibold uppercase tracking-wide text-(--ui-text-tertiary)', children: `已处理（${processed.length}）` }),
              processed.slice(0, 5).map(s => jsx(MergedSessionCard, { key: s.id || s.title, s, onUndo: doUndo }))
            ]
          })
        : null
    ]
  })
}

function WorkbenchChip() {
  const { data } = useQuery({
    queryKey: [ID, 'workbench'],
    queryFn: () => rest('/workbench'),
    refetchInterval: 60000,
    retry: 0
  })
  const matters = Array.isArray(data?.matters) ? data.matters.length : null
  const sessions = data?.session_work?.count ?? null
  const text = matters == null ? '律师台 离线' : `律师台 ${matters} 案 · ${sessions ?? 0} 线索`
  const cls = matters == null
    ? 'text-(--ui-text-tertiary)'
    : (data && data.warnings && data.warnings.length ? 'text-(--ui-orange)' : 'text-(--ui-text-secondary)')
  return jsx(Tip, {
    label: matters == null
      ? '律师工作台：数据未就绪'
      : `律师工作台：${matters} 项已确认事项 · ${sessions ?? 0} 项会话工作线索 · 只读`,
    children: jsx('button', {
      type: 'button',
      className: cn('inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] transition-colors hover:bg-(--chrome-action-hover) hover:text-foreground', cls),
      onClick: () => {
        if (matters == null) {
          host.notify({ kind: 'warning', message: '律师工作台数据未就绪，请重启 Hermes 或检查 gateway 插件。' })
        } else {
          host.notify({ kind: 'info', message: `律师工作台：${matters} 项已确认事项 · ${sessions ?? 0} 项会话工作线索（只读）` })
        }
      },
      children: text
    })
  })
}

export default {
  id: ID,
  name: '律师工作台',
  register(ctx) {
    rest = ctx.rest.bind(ctx)
    ctx.register({
      id: 'pane',
      area: 'panes',
      title: '律师工作台',
      data: { placement: 'right', width: '320px' },
      render: () => jsx(WorkbenchPane, {})
    })
    ctx.register({
      id: 'chip',
      area: 'statusBar.right',
      order: 95,
      render: () => jsx(WorkbenchChip, {})
    })
  }
}
