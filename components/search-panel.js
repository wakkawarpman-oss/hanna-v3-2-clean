'use strict'

const fs = require('node:fs')
const blessed = require('blessed')
const contrib = require('blessed-contrib')

class SafeParser {
  safeRegex (text, regex) {
    try {
      const match = text.match(regex)
      return match ? match[0] : ''
    } catch {
      return ''
    }
  }

  sanitizeInput (input) {
    if (input == null) {
      throw new Error('INVALID_INPUT: input is null or undefined')
    }

    const raw = Buffer.isBuffer(input) ? input.toString('utf8') : input
    if (typeof raw !== 'string') {
      throw new Error('INVALID_INPUT: expected string or Buffer')
    }

    return raw
      .normalize('NFC')
      .replace(/[\uFEFF]/g, '')
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, ' ')
      .replace(/[ \t]+/g, ' ')
      .trim()
  }

  extractPhone (text) {
    const candidates = [
      ...(text.match(/\+\d[\d\s().-]{8,20}\d/g) || []),
      ...(text.match(/\b0\d(?:[\s().-]?\d){8}\b/g) || [])
    ]

    for (const rawCandidate of candidates) {
      const compactDigits = rawCandidate.replace(/\D/g, '')
      const normalized = rawCandidate.trim().startsWith('+') ? `+${compactDigits}` : compactDigits

      if (/^\+\d{10,15}$/.test(normalized) || /^0\d{9}$/.test(normalized)) {
        return normalized
      }
    }

    return ''
  }

  collectErrors (parsed) {
    const errors = []
    if (!parsed.fio) errors.push('NO_FIO')
    if (!parsed.address) errors.push('NO_ADDRESS')
    if (!parsed.phone) errors.push('NO_PHONE')
    if (parsed.fio && parsed.fio.length > 100) errors.push('FIO_TOO_LONG')
    return errors
  }

  parseSearchInput (input) {
    try {
      const cleanText = this.sanitizeInput(input)
      const emptyParsed = { fio: '', birthYear: '', address: '', city: '', phone: '', fop: '' }

      if (cleanText.length === 0) {
        return {
          raw: '',
          parsed: emptyParsed,
          confidence: 0,
          errors: ['EMPTY_INPUT'],
          status: 'EMPTY'
        }
      }

      const lines = cleanText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
      let fioCandidate = ''

      for (const line of lines) {
        const match = line.match(/^([A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+(?:\s+[A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+){1,3})/u)
        if (match && !/\d/.test(match[1])) {
          fioCandidate = match[1]
          break
        }
      }

      if (!fioCandidate) {
        fioCandidate = this.safeRegex(cleanText, /([A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+\s+){1,3}[A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+/u)
      }

      const birthYear = this.safeRegex(cleanText, /\b(19|20)\d{2}\b/)
      const address = this.safeRegex(cleanText, /(вул\.?|ул\.?|вулиця|улица|просп\.?|проспект|street|st\.?)\s*[^,\n]+/iu)
      const city = this.safeRegex(cleanText, /Київ|Киев|Kharkiv|Kharkov|Харків|Харьков|Одеса|Одесса|Львів|Львов|Дніпро|Днепр|Dnipro|Lviv|Odesa/iu)
      const phone = this.extractPhone(cleanText)
      const fopRaw = this.safeRegex(cleanText, /ФОП|FOP|підприємець|предприниматель|entrepreneur/iu)
      const fop = fopRaw ? 'ФОП' : ''

      const hasStreetTokenInFio = /(вул\.?|ул\.?|вулиця|улица|street|st\.?|просп\.?|проспект)/iu.test(fioCandidate)
      const fio = fioCandidate && (hasStreetTokenInFio || (address && address.includes(fioCandidate))) ? '' : fioCandidate

      const parsed = { fio, birthYear, address, city, phone, fop }
      const confidence = Object.values(parsed).filter(Boolean).length
      const errors = confidence === 0 ? ['NO_MATCHES'] : this.collectErrors(parsed)
      const status = confidence >= 3 ? 'HIGH' : confidence >= 1 ? 'LOW' : 'EMPTY'

      return {
        raw: cleanText,
        parsed,
        confidence,
        errors,
        status
      }
    } catch (error) {
      return {
        raw: input != null ? String(input) : '',
        parsed: { fio: '', birthYear: '', address: '', city: '', phone: '', fop: '' },
        confidence: 0,
        errors: [error.message || 'PARSER_ERROR'],
        status: 'ERROR'
      }
    }
  }

  async routeToTools (parsedData) {
    const tools = []

    if (parsedData.parsed.fio) {
      tools.push({ name: 'ФІО Search', route: '/adapters/fio-search', status: '🟢' })
    }
    if (parsedData.parsed.address) {
      tools.push({ name: 'Адресний пошук', route: '/adapters/address-lookup', status: '🟢' })
    }
    if (parsedData.parsed.birthYear) {
      tools.push({ name: 'ДР/РІК', route: '/adapters/birthyear-check', status: '🟢' })
    }
    if (parsedData.parsed.phone) {
      tools.push({ name: 'Телефон', route: '/adapters/phone-lookup', status: '🟢' })
    }
    if (parsedData.parsed.fop) {
      tools.push({ name: 'ФОП/ЄДР', route: '/adapters/fop-search', status: '🟢' })
    }

    return tools
  }
}

class DebugParser extends SafeParser {
  constructor (debug = false) {
    super()
    this.debug = debug || process.env.DEBUG === '1'
    this.debugLog = []
  }

  parseSearchInput (text, options = {}) {
    const start = Date.now()
    const debugId = options.debugId || `DBG-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

    if (this.debug) {
      this.debugLog.push({
        id: debugId,
        timestamp: new Date().toISOString(),
        inputLength: text?.length || 0,
        stage: 'START'
      })
    }

    const result = super.parseSearchInput(text)

    if (this.debug) {
      this.debugLog.push({
        id: debugId,
        timestamp: new Date().toISOString(),
        stage: result.status === 'ERROR' ? 'ERROR' : 'PARSED',
        duration: Date.now() - start,
        confidence: result.confidence,
        parsedFields: Object.keys(result.parsed).filter((k) => result.parsed[k]),
        errors: result.errors || []
      })
    }

    return result
  }

  getDebugReport (casePrefix = 'DBG-') {
    return this.debugLog.filter((log) => log.id.startsWith(casePrefix))
  }

  dumpDebug (filename = `debug-${Date.now()}.json`) {
    fs.writeFileSync(filename, JSON.stringify(this.debugLog, null, 2) + '\n')
    return filename
  }
}

class SearchPanel extends SafeParser {
  constructor (screen, apiClient, onLog) {
    super()
    this.screen = screen || null
    this.api = apiClient || null
    this.onLog = typeof onLog === 'function' ? onLog : () => {}
    this.results = []

    if (!this.screen) {
      this.searchBox = null
      this.resultsBox = null
      this.toolStatus = null
      return
    }

    this.searchBox = blessed.textbox({
      parent: screen,
      top: '28%',
      left: '18%',
      width: '64%',
      height: 5,
      label: ' OSINT ПОШУК ',
      border: { type: 'line', fg: 'green' },
      style: { fg: 'white', bg: 'black', border: { fg: 'green' }, focus: { border: { fg: 'cyan' } } },
      inputOnFocus: true,
      keys: true,
      mouse: true,
      tags: true,
      hidden: true,
      value: ''
    })

    this.resultsBox = contrib.table({
      parent: screen,
      top: '38%',
      left: '8%',
      width: '66%',
      height: '48%',
      label: ' РЕЗУЛЬТАТИ ',
      columnSpacing: 2,
      columnWidth: [20, 38, 10],
      border: { type: 'line', fg: 'green' },
      fg: 'white',
      hidden: true
    })

    this.toolStatus = blessed.box({
      parent: screen,
      top: '38%',
      left: '75%',
      width: '17%',
      height: '48%',
      label: ' АКТИВНІ ІНСТРУМЕНТИ ',
      border: { type: 'line', fg: 'green' },
      style: { fg: 'white', bg: 'black', border: { fg: 'green' } },
      tags: true,
      content: 'Готово до пошуку',
      hidden: true
    })

    this.setEmptyResults()
    this.bindEvents()
  }

  setEmptyResults () {
    if (!this.resultsBox) {
      return
    }

    this.resultsBox.setData({
      headers: ['Інструмент', 'Результат', 'Точність'],
      data: [['-', 'Готово до пошуку', '-']]
    })
  }

  async executeSearch (input) {
    if (!this.screen || !this.resultsBox || !this.toolStatus) {
      return
    }

    const parsed = this.parseSearchInput(input)
    this.showParsedData(parsed)

    if (parsed.confidence < 2) {
      this.resultsBox.setData({
        headers: ['Інструмент', 'Результат', 'Точність'],
        data: [['❌', 'Недостатньо даних', 'Додайте ФІО/адресу/рік']]
      })
      this.screen.render()
      return
    }

    const activeTools = await this.routeToTools(parsed)
    this.updateToolStatus(activeTools)

    const results = await this.fetchToolResults(parsed, activeTools)
    this.displayResults(results)
  }

  showParsedData (parsed) {
    if (!this.toolStatus || !this.screen) {
      return
    }

    const lines = [
      `{bold}Сирий запит{/}: ${parsed.raw || '—'}`,
      '',
      `{bold}ФІО{/}: ${parsed.parsed.fio || '—'}`,
      `{bold}Рік{/}: ${parsed.parsed.birthYear || '—'}`,
      `{bold}Місто{/}: ${parsed.parsed.city || '—'}`,
      `{bold}Адреса{/}: ${parsed.parsed.address || '—'}`,
      `{bold}Телефон{/}: ${parsed.parsed.phone || '—'}`,
      `{bold}ФОП{/}: ${parsed.parsed.fop ? 'Так' : '—'}`
    ]
    this.toolStatus.setContent(lines.join('\n'))
    this.screen.render()
  }

  async fetchToolResults (parsed, tools) {
    const settled = await Promise.allSettled(
      tools.map(async (tool) => {
        const data = await this.mockApiCall(parsed, tool.route)
        return {
          tool: tool.name,
          status: 'completed',
          data,
          confidence: Math.floor(Math.random() * 31) + 65
        }
      })
    )

    return settled
      .filter((result) => result.status === 'fulfilled')
      .map((result) => result.value)
      .sort((a, b) => b.confidence - a.confidence)
  }

  mockApiCall (parsed, route) {
    if (this.api && typeof this.api.search === 'function') {
      return this.api.search({ parsed, route })
    }

    return new Promise((resolve) => {
      setTimeout(() => {
        const sample = `${parsed.parsed.fio || 'Невідомо'} | ${parsed.parsed.birthYear || 'рік ?'} | ${parsed.parsed.city || 'місто ?'} | ${parsed.parsed.phone || 'телефон ?'}`
        resolve(sample)
      }, 300 + Math.random() * 900)
    })
  }

  updateToolStatus (tools) {
    if (!this.toolStatus || !this.screen) {
      return
    }

    const statusLines = tools.length
      ? tools.map((tool) => `${tool.status} ${tool.name}`)
      : ['Інструменти не визначені']

    this.toolStatus.setContent(statusLines.join('\n'))
    this.screen.render()
  }

  displayResults (results) {
    if (!this.resultsBox || !this.screen) {
      return
    }

    const rows = results.map((result) => [
      result.tool,
      result.data.length > 36 ? `${result.data.slice(0, 33)}...` : result.data,
      `${result.confidence}%`
    ])

    this.resultsBox.setData({
      headers: ['Інструмент', 'Результат', 'Точність'],
      data: rows.length ? rows : [['-', 'Немає результатів', '-']]
    })
    this.onLog(`Search completed: ${rows.length} tool results`)
    this.screen.render()
  }

  open () {
    if (!this.searchBox || !this.resultsBox || !this.toolStatus || !this.screen) {
      return
    }

    this.searchBox.show()
    this.resultsBox.show()
    this.toolStatus.show()
    this.searchBox.focus()
    this.screen.render()
  }

  close () {
    if (!this.searchBox || !this.resultsBox || !this.toolStatus || !this.screen) {
      return
    }

    this.searchBox.hide()
    this.resultsBox.hide()
    this.toolStatus.hide()
    this.screen.render()
  }

  bindEvents () {
    if (!this.searchBox || !this.toolStatus || !this.screen) {
      return
    }

    this.searchBox.key(['enter'], async () => {
      const query = this.searchBox.getValue()
      if (!query.trim()) {
        return
      }
      await this.executeSearch(query)
    })

    this.searchBox.key(['C-c'], () => {
      this.searchBox.clearValue()
      this.setEmptyResults()
      this.toolStatus.setContent('Готово до пошуку')
      this.screen.render()
    })

    this.searchBox.key(['C-enter', 'C-return'], () => {
      this.searchBox.setValue('Пелешенко Дмитро Валерійович 1972 Харків Гв. Широнинцев 49 ФОП 0958042036')
      this.screen.render()
    })

    this.searchBox.key(['escape'], () => {
      this.close()
    })
  }
}

function initSearch (screen, apiClient, onLog) {
  const panel = new SearchPanel(screen, apiClient, onLog)

  setTimeout(() => {
    panel.searchBox.setValue('Пелешенко Дмитро Валерійович 1972 Харків, Гв. Широнинцев 49 0958042036')
    if (!panel.searchBox.hidden) {
      panel.screen.render()
    }
  }, 1000)

  return panel
}

module.exports = {
  SafeParser,
  DebugParser,
  SearchPanel,
  initSearch
}
