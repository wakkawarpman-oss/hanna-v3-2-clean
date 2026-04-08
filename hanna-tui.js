'use strict'

const blessed = require('blessed')
const contrib = require('blessed-contrib')
const { initSearch, DebugParser } = require('./components/search-panel')
const { DebugTui } = require('./components/debug-tui')

const COLORS = {
  primary: 'green',
  warning: 'yellow',
  danger: 'red',
  text: 'white'
}

const COMPONENTS = [
  { name: 'Auth API', status: 'ACTIVE' },
  { name: 'Adapter Core', status: 'ACTIVE' },
  { name: 'RBAC Engine', status: 'WARNING' },
  { name: 'Tenant DB', status: 'ACTIVE' },
  { name: 'OSINT Queue', status: 'ACTIVE' }
]

const SESSIONS = [
  'user1@example.com',
  'user2@gmail.com',
  'admin@admin.com'
]

function nowIsoMinute () {
  return new Date().toISOString().slice(0, 16).replace('T', ' ')
}

function timeLabel () {
  const d = new Date()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const tz = Intl.DateTimeFormat('en', { timeZoneName: 'short' })
    .formatToParts(d)
    .find((p) => p.type === 'timeZoneName')?.value || 'LOCAL'
  return `${hh}:${mm}\n${tz}`
}

function statusText (status) {
  if (status === 'ACTIVE') return '{green-fg}ACTIVE{/}'
  if (status === 'WARNING') return '{yellow-fg}WARNING{/}'
  return '{red-fg}ERROR{/}'
}

function buildScreen () {
  const screen = blessed.screen({
    smartCSR: true,
    title: 'HANNA OSINT & KESB Monitor'
  })

  const grid = new contrib.grid({ rows: 24, cols: 24, screen })

  const header = grid.set(0, 0, 3, 24, blessed.box, {
    label: ' HANNA OSINT & KESB ',
    border: { type: 'line', fg: COLORS.primary },
    style: { fg: COLORS.primary },
    content: '{center}Gate 2 / Step 1 monitor{/center}',
    tags: true
  })

  const sessions = grid.set(3, 0, 21, 6, blessed.list, {
    label: ' Sessions ',
    border: { type: 'line', fg: COLORS.primary },
    style: {
      fg: COLORS.text,
      selected: { bg: 'blue' }
    },
    keys: true,
    mouse: true,
    vi: true,
    items: SESSIONS
  })

  const table = grid.set(3, 6, 12, 12, contrib.table, {
    label: ' Components ',
    keys: true,
    fg: COLORS.text,
    interactive: false,
    columnSpacing: 2,
    columnWidth: [14, 12, 20],
    border: { type: 'line', fg: COLORS.primary }
  })

  const rps = grid.set(3, 18, 12, 6, contrib.sparkline, {
    label: ' RPS ',
    tags: true,
    border: { type: 'line', fg: COLORS.primary },
    style: {
      line: 'cyan',
      text: COLORS.text,
      baseline: 'black'
    }
  })

  const logs = grid.set(15, 6, 9, 12, blessed.log, {
    label: ' Event Logs ',
    border: { type: 'line', fg: COLORS.primary },
    style: { fg: COLORS.text },
    tags: true,
    mouse: true,
    keys: true,
    vi: true,
    scrollable: true,
    alwaysScroll: true,
    scrollbar: {
      ch: ' ',
      inverse: true
    }
  })

  const resources = grid.set(15, 18, 5, 6, contrib.bar, {
    label: ' Resources ',
    border: { type: 'line', fg: COLORS.primary },
    barWidth: 5,
    barSpacing: 3,
    xOffset: 0,
    maxHeight: 9
  })

  const quick = grid.set(20, 18, 4, 6, blessed.box, {
    label: ' Quick Actions ',
    border: { type: 'line', fg: COLORS.primary },
    tags: true,
    content: '{center}Tab: next\nq: quit\nCtrl+A: analyze\nCtrl+E: export{/center}'
  })

  const clock = grid.set(20, 6, 4, 4, blessed.box, {
    label: ' Time ',
    border: { type: 'line', fg: COLORS.primary },
    tags: true,
    content: `{center}${timeLabel()}{/center}`
  })

  const statusLegend = grid.set(20, 10, 4, 8, blessed.box, {
    label: ' Status Legend ',
    border: { type: 'line', fg: COLORS.primary },
    tags: true,
    content: '{green-fg}ACTIVE{/} {yellow-fg}WARNING{/} {red-fg}ERROR{/}'
  })

  void header
  void quick
  void statusLegend

  return {
    screen,
    sessions,
    table,
    rps,
    logs,
    resources,
    clock
  }
}

function startTui () {
  const ui = buildScreen()
  const { screen, sessions, table, rps, logs, resources, clock } = ui
  const debugParser = new DebugParser(process.env.DEBUG === '1' || process.env.TUI_DEBUG === '1')
  const debugTui = new DebugTui(screen, debugParser, (line) => {
    logs.log(`[${nowIsoMinute()}] ${line}`)
  })
  let debugMode = process.env.TUI_DEBUG === '1'

  const searchPanel = initSearch(screen, null, (line) => {
    logs.log(`[${nowIsoMinute()}] ${line}`)
  })

  const focusables = [sessions, logs]
  let focusIndex = 0
  focusables[focusIndex].focus()

  const rpsSeries = [0, 2, 5, 3, 7, 12, 8, 15, 10]

  function renderComponents () {
    table.setData({
      headers: ['Component', 'Status', 'Updated'],
      data: COMPONENTS.map((c) => [c.name, statusText(c.status), nowIsoMinute()])
    })
  }

  function renderRps () {
    rps.setData(['RPS'], [rpsSeries])
  }

  function renderResources () {
    const cpu = 20 + Math.floor(Math.random() * 50)
    const ram = 40 + Math.floor(Math.random() * 50)
    resources.setData({
      titles: ['CPU', 'RAM'],
      data: [cpu, ram]
    })
  }

  function addLog (line) {
    logs.log(line)
  }

  function tickClock () {
    clock.setContent(`{center}${timeLabel()}{/center}`)
  }

  function tickMetrics () {
    const next = Math.floor(Math.random() * 20)
    rpsSeries.shift()
    rpsSeries.push(next)
    renderRps()
  }

  function tickComponentStatus () {
    const idx = Math.floor(Math.random() * COMPONENTS.length)
    const roll = Math.random()
    COMPONENTS[idx].status = roll > 0.8 ? 'WARNING' : 'ACTIVE'
    renderComponents()
  }

  function tickLogs () {
    const events = [
      'User login success',
      'Adapter run accepted',
      'Permission check passed',
      'Rate limit warning',
      'Healthcheck OK',
      'Token validation failed'
    ]
    const message = events[Math.floor(Math.random() * events.length)]
    addLog(`[${nowIsoMinute()}] ${message}`)
  }

  renderComponents()
  renderRps()
  renderResources()
  addLog('[startup] HANNA TUI initialized')
  tickClock()

  screen.key(['escape', 'q', 'C-c'], () => process.exit(0))

  screen.key(['tab'], () => {
    focusIndex = (focusIndex + 1) % focusables.length
    focusables[focusIndex].focus()
    screen.render()
  })

  screen.key(['C-a'], () => {
    addLog(`[${nowIsoMinute()}] Manual action: ANALYZE`)
    screen.render()
  })

  screen.key(['C-e'], () => {
    addLog(`[${nowIsoMinute()}] Manual action: EXPORT`)
    screen.render()
  })

  screen.key(['C-s'], () => {
    searchPanel.open()
    addLog(`[${nowIsoMinute()}] Search panel opened`)
    screen.render()
  })

  screen.key(['C-d'], () => {
    debugTui.open()
    addLog(`[${nowIsoMinute()}] Debug panel opened`)
    screen.render()
  })

  screen.key(['f12'], () => {
    debugMode = !debugMode
    if (debugMode) {
      debugTui.open()
    } else {
      debugTui.close()
    }
    addLog(`[${nowIsoMinute()}] Debug mode ${debugMode ? 'ON' : 'OFF'}`)
    screen.render()
  })

  sessions.on('select item', (item) => {
    addLog(`[${nowIsoMinute()}] Session selected: ${item.getText()}`)
    screen.render()
  })

  setInterval(() => {
    tickClock()
    screen.render()
  }, 1000)

  setInterval(() => {
    tickMetrics()
    renderResources()
    screen.render()
  }, 2000)

  setInterval(() => {
    tickComponentStatus()
    tickLogs()
    screen.render()
  }, 5000)

  screen.render()
}

if (require.main === module) {
  startTui()
}

module.exports = {
  startTui
}
