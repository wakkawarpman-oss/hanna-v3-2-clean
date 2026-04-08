'use strict'

const fs = require('node:fs')
const path = require('node:path')
const blessed = require('blessed')
const contrib = require('blessed-contrib')
const { initSearch, DebugParser } = require('./components/search-panel')
const { CalibratedParser, DEFAULT_CONFIG } = require('./components/calibrated-parser')
const { DebugTui } = require('./components/debug-tui')
const { UltraPerfTui } = require('./components/ultra-perf-tui')
const { BehavioralMetrics } = require('./components/behavioral-metrics')

const COLORS = {
  primary: 'cyan',
  accent: 'magenta',
  success: 'green',
  warning: 'yellow',
  danger: 'red',
  text: 'white',
  dim: 'gray',
  highlight: 'blue'
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

function loadCalibrationConfig (enabled) {
  if (!enabled) {
    return DEFAULT_CONFIG
  }

  try {
    const configPath = path.resolve('config.calibrated.json')
    const raw = fs.readFileSync(configPath, 'utf8')
    const parsed = JSON.parse(raw)
    return {
      parser: { ...DEFAULT_CONFIG.parser, ...(parsed.parser || {}) },
      search: { ...DEFAULT_CONFIG.search, ...(parsed.search || {}) },
      tui: { ...DEFAULT_CONFIG.tui, ...(parsed.tui || {}) },
      behavioral: { ...DEFAULT_CONFIG.behavioral, ...(parsed.behavioral || {}) }
    }
  } catch {
    return DEFAULT_CONFIG
  }
}

function buildScreen (options = {}) {
  const compactMode = options.compactMode === true

  const screen = blessed.screen({
    smartCSR: true,
    title: 'HANNA OSINT & KESB Monitor'
  })

  const grid = new contrib.grid({ rows: 24, cols: 24, screen })

  const header = grid.set(0, 0, 3, 24, blessed.box, {
    label: ' HANNA OSINT & KESB ',
    border: { type: 'line', fg: COLORS.primary },
    style: { fg: COLORS.primary },
    content: `{center}{cyan-fg}{bold}██╗  ██╗ █████╗ ███╗   ██╗███╗   ██╗ █████╗{/bold}{/cyan-fg}\n{magenta-fg}OSINT & КІБЕРРОЗВІДКА{/magenta-fg} | Gate 2 / Step 1 monitor${compactMode ? ' | COMPACT' : ''}{/center}`,
    tags: true
  })

  const sessions = grid.set(3, 0, 21, 6, blessed.list, {
    label: ' Sessions ',
    border: { type: 'line', fg: COLORS.accent },
    style: {
      fg: COLORS.text,
      selected: { bg: 'blue', fg: 'white' }
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
    border: { type: 'line', fg: COLORS.success }
  })

  const rps = grid.set(3, 18, 12, 6, contrib.sparkline, {
    label: ' RPS ',
    tags: true,
    border: { type: 'line', fg: COLORS.warning },
    style: {
      line: 'magenta',
      text: COLORS.text,
      baseline: 'black'
    }
  })

  const logs = grid.set(15, 6, 9, 12, blessed.log, {
    label: ' Event Logs ',
    border: { type: 'line', fg: COLORS.primary },
    style: { fg: '#7fdbff' },
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
    border: { type: 'line', fg: COLORS.accent },
    barWidth: 5,
    barSpacing: 3,
    xOffset: 0,
    maxHeight: 9
  })

  const quick = grid.set(20, 18, 4, 6, blessed.box, {
    label: ' Quick Actions ',
    border: { type: 'line', fg: COLORS.warning },
    tags: true,
    content: compactMode
      ? '{center}Tab/q\nCtrl+A\nCtrl+E{/center}'
      : '{center}Tab: next\nq: quit\nCtrl+A: analyze\nCtrl+E: export{/center}'
  })

  const clock = grid.set(20, 6, 4, 4, blessed.box, {
    label: ' Time ',
    border: { type: 'line', fg: COLORS.success },
    tags: true,
    content: `{center}${timeLabel()}{/center}`
  })

  const statusLegend = grid.set(20, 10, 4, 8, blessed.box, {
    label: ' Status Legend ',
    border: { type: 'line', fg: COLORS.highlight },
    tags: true,
    content: '{green-fg}{bold}ACTIVE{/} {yellow-fg}{bold}WARNING{/} {red-fg}{bold}ERROR{/}'
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
  const calibratedEnabled = process.env.CALIBRATED === '1'
  const calibration = loadCalibrationConfig(calibratedEnabled)
  const ui = buildScreen({ compactMode: calibration.tui.compactMode })
  const { screen, sessions, table, rps, logs, resources, clock } = ui
  const frameBudget = Math.max(1, Math.round(1000 / Math.max(15, Number(calibration.tui.fpsTarget) || 60)))
  const ultraPerf = process.env.TUI_ULTRA === '1' ? new UltraPerfTui(screen, { frameBudget }) : null
  const behavioralEnabled = process.env.BEHAVIORAL === '1'
  const metrics = behavioralEnabled ? new BehavioralMetrics() : null
  let metricsPanel = null
  const noiseLevel = Math.min(0.25, Math.max(0.01, Number(calibration.behavioral.noiseLevel) || 0.1))
  const calibratedParser = calibratedEnabled ? new CalibratedParser(path.resolve('config.calibrated.json')) : null

  if (behavioralEnabled) {
    metricsPanel = blessed.box({
      parent: screen,
      top: 0,
      left: '70%',
      width: '30%',
      height: 6,
      label: ' BEHAVIORAL ',
      border: { type: 'line', fg: 'cyan' },
      style: { fg: 'white' },
      content: 'Engagement: 0/100\nDwell: 0s\nQueries: 0\nClicks: 0\nScrolls: 0'
    })
    metrics.attachPanel(metricsPanel)
  }

  function requestRender (widget) {
    if (ultraPerf) {
      ultraPerf.markDirty(widget)
      return
    }
    screen.render()
  }
  const debugParser = new DebugParser(process.env.DEBUG === '1' || process.env.TUI_DEBUG === '1')
  const debugTui = new DebugTui(screen, debugParser, (line) => {
    logs.log(`[${nowIsoMinute()}] ${line}`)
  })
  let debugMode = process.env.TUI_DEBUG === '1'

  const searchPanel = initSearch(screen, null, (line) => {
    logs.log(`[${nowIsoMinute()}] ${line}`)
    if (metrics && line.startsWith('Search completed')) {
      metrics.trackAction('search')
    }
  }, { parser: calibratedParser })

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
    const base = Math.floor(Math.random() * 20)
    const noisy = Math.max(0, Math.round(base + ((Math.random() * 2) - 1) * 20 * noiseLevel))
    const next = noisy
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
  addLog(`[startup] HANNA TUI initialized${calibratedEnabled ? ' [CALIBRATED]' : ''}`)
  if (calibratedEnabled) {
    addLog(`[startup] Calibration loaded: fps=${calibration.tui.fpsTarget}, compact=${calibration.tui.compactMode}, noise=${noiseLevel}`)
  }
  tickClock()

  screen.key(['escape', 'q', 'C-c'], () => process.exit(0))

  screen.key(['tab'], () => {
    focusIndex = (focusIndex + 1) % focusables.length
    focusables[focusIndex].focus()
    if (metrics) metrics.trackAction('navigate')
    requestRender(focusables[focusIndex])
  })

  screen.key(['C-a'], () => {
    addLog(`[${nowIsoMinute()}] Manual action: ANALYZE`)
    if (metrics) metrics.trackAction('result_click')
    requestRender(logs)
  })

  screen.key(['C-e'], () => {
    addLog(`[${nowIsoMinute()}] Manual action: EXPORT`)
    if (metrics) metrics.trackAction('result_click')
    requestRender(logs)
  })

  screen.key(['C-s'], () => {
    searchPanel.open()
    addLog(`[${nowIsoMinute()}] Search panel opened`)
    if (metrics) metrics.trackAction('search')
    requestRender(logs)
  })

  screen.key(['C-d'], () => {
    debugTui.open()
    addLog(`[${nowIsoMinute()}] Debug panel opened`)
    if (metrics) metrics.trackAction('navigate')
    requestRender(logs)
  })

  screen.key(['f12'], () => {
    debugMode = !debugMode
    if (debugMode) {
      debugTui.open()
    } else {
      debugTui.close()
    }
    addLog(`[${nowIsoMinute()}] Debug mode ${debugMode ? 'ON' : 'OFF'}`)
    requestRender(logs)
  })

  sessions.on('select item', (item) => {
    addLog(`[${nowIsoMinute()}] Session selected: ${item.getText()}`)
    if (metrics) metrics.trackAction('navigate')
    requestRender(logs)
  })

  screen.key(['up', 'down', 'pageup', 'pagedown'], () => {
    if (metrics) metrics.trackAction('scroll')
  })

  setInterval(() => {
    tickClock()
    requestRender(clock)
  }, 1000)

  setInterval(() => {
    tickMetrics()
    renderResources()
    requestRender(rps)
  }, 2000)

  setInterval(() => {
    tickComponentStatus()
    tickLogs()
    requestRender(table)
  }, 5000)

  screen.render()
}

if (require.main === module) {
  startTui()
}

module.exports = {
  startTui
}
