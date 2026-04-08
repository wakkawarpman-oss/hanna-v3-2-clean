'use strict'

const blessed = require('blessed')
const contrib = require('blessed-contrib')

class SearchPanel {
  constructor (screen, apiClient, onLog) {
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

  extractPhone (text) {
    const candidates = [
      ...(text.match(/\+\d[\d\s().-]{8,20}\d/g) || []),
      ...(text.match(/\b0\d(?:[\s().-]?\d){8}\b/g) || [])
    ]

    for (const rawCandidate of candidates) {
      const compactDigits = rawCandidate.replace(/\D/g, '')
      const normalized = rawCandidate.trim().startsWith('+')
        ? `+${compactDigits}`
        : compactDigits

      if (/^\+\d{10,15}$/.test(normalized) || /^0\d{9}$/.test(normalized)) {
        return normalized
      }
    }

    return ''
  }

  parseSearchInput (text) {
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    let fioCandidate = ''

    for (const line of lines) {
      const match = line.match(/^([A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+(?:\s+[A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+){1,3})/u)
      if (match && !/\d/.test(match[1])) {
        fioCandidate = match[1]
        break
      }
    }

    if (!fioCandidate) {
      fioCandidate = text.match(/([A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+\s+){1,3}[A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]+/u)?.[0] || ''
    }

    const birthYear = text.match(/\b(19|20)\d{2}\b/)?.[0] || ''
    const address = text.match(/(вул\.?|ул\.?|вулиця|улица|просп\.?|проспект|street|st\.?)\s*[^,\n]+/iu)?.[0] || ''
    const city = text.match(/Київ|Киев|Kharkiv|Kharkov|Харків|Харьков|Одеса|Одесса|Львів|Львов|Дніпро|Днепр|Dnipro|Lviv|Odesa/iu)?.[0] || ''
    const phone = this.extractPhone(text)
    const fopRaw = text.match(/ФОП|FOP|підприємець|предприниматель|entrepreneur/iu)?.[0] || ''
    const fop = fopRaw ? 'ФОП' : ''

    const hasStreetTokenInFio = /(вул\.?|ул\.?|вулиця|улица|street|st\.?|просп\.?|проспект)/iu.test(fioCandidate)
    const fio = fioCandidate && (hasStreetTokenInFio || (address && address.includes(fioCandidate))) ? '' : fioCandidate

    const parsed = { fio, birthYear, address, city, phone, fop }
    const confidence = Object.values(parsed).filter(Boolean).length

    return {
      raw: text.trim(),
      parsed,
      confidence
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
  SearchPanel,
  initSearch
}
