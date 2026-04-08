#!/usr/bin/env node
'use strict'

const path = require('node:path')
const { DebugParser } = require('../components/search-panel')

const parser = new DebugParser(true)

const samples = [
  'Пелешенко Дмитро Валерійович 1972 Харків Гв. Широнинцев 49',
  '0958042036 22.07.1973 ул. Бучмы 32Б',
  'Коваленко Петро ФОП вул. Сумська 0671234567'
]

for (const sample of samples) {
  parser.parseSearchInput(sample)
}

const target = path.join('test', `debug-${Date.now()}.json`)
const file = parser.dumpDebug(target)
console.log(`Debug data written to ${file}`)
