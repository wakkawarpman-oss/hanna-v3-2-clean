#!/usr/bin/env node
'use strict'

const { SearchPanel } = require('../components/search-panel')

const panel = new SearchPanel()

const testData = [
  `Пелешенко Дмитро Валерійович 1972 г. р.\nБыл прописан Харьков Ул. Гв. Широнинцев 49`,
  `22.07.1973 г. Харьков, ул. Бучмы, 32Б 0958042036`,
  `Коваленко Петро Миколайович 1985 ФОП Харків`
]

console.log('OSINT Parser Tester')

testData.forEach((data, i) => {
  const parsed = panel.parseSearchInput(data)
  console.log(`\nCase ${i + 1}:`)
  console.log(`Input: "${data}"`)
  console.log('Parsed:', parsed.parsed)
  console.log('Confidence:', parsed.confidence)
})
