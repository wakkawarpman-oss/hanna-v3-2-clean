#!/usr/bin/env node
'use strict'

const { ParserPool } = require('../components/parser-pool')

async function main () {
  const concurrent = Number(process.argv[2] || 100)
  const pool = new ParserPool(4)

  const payload = 'Пелешенко Дмитро Валерійович 1972 Харків вул. Широнинцев 49 0958042036'
  const start = Date.now()

  await Promise.all(Array.from({ length: concurrent }, () => pool.parse(payload)))
  const elapsedMs = Date.now() - start

  await pool.destroy()

  console.log(JSON.stringify({ concurrent, elapsedMs }, null, 2))
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
