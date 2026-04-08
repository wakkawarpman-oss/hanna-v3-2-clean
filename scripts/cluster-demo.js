#!/usr/bin/env node
'use strict'

const { SearchResults } = require('../components/smart-search')

const input = [
  { parsed: { fio: 'Пелешенко Дмитро', birthYear: '1972', city: 'Харків' }, score: 5.2, tool: 'ФІО Search' },
  { parsed: { fio: 'Пелешенко Дмитро', birthYear: '1972', city: 'Харків' }, score: 4.8, tool: 'Адресний пошук' },
  { parsed: { fio: 'Коваленко Петро', birthYear: '1980', city: 'Київ' }, score: 3.1, tool: 'Телефон' }
]

const clusters = new SearchResults().groupResults(input)
console.log(JSON.stringify(clusters, null, 2))
