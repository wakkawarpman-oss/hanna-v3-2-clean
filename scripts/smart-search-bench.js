#!/usr/bin/env node
'use strict'

const { SmartSearch } = require('../components/smart-search')

const smart = new SmartSearch()
const parsed = {
  fio: 'Пелешенко Дмитро Валерійович',
  birthYear: '1972',
  city: 'Харків',
  address: 'вул. Широнинцев 49',
  phone: '0958042036'
}

const queries = Array.from({ length: 1000 }, (_, i) =>
  i % 2 === 0 ? 'Пелешенко Дмитро Харків 1972' : 'Peleshenko Dmytro Kharkiv'
)

const start = process.hrtime.bigint()
let total = 0
for (const q of queries) {
  total += smart.scoreResult(parsed, q).score
}
const end = process.hrtime.bigint()
const ms = Number(end - start) / 1e6

console.log(JSON.stringify({
  queries: queries.length,
  avgMsPerQuery: Number((ms / queries.length).toFixed(3)),
  totalScore: Number(total.toFixed(2))
}, null, 2))
