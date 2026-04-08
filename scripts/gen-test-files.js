#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')

const outDir = path.resolve('test/data')
fs.mkdirSync(outDir, { recursive: true })

function generateFile (name, approxMb) {
  const line = 'Пелешенко Дмитро Валерійович 1972 Харків вул. Широнинцев 49 0958042036 ФОП\n'
  const targetBytes = approxMb * 1024 * 1024
  const fd = fs.openSync(path.join(outDir, name), 'w')

  let written = 0
  while (written < targetBytes) {
    fs.writeSync(fd, line)
    written += Buffer.byteLength(line)
  }

  fs.closeSync(fd)
}

generateFile('10mb.txt', 10)
generateFile('100mb.txt', 100)
console.log('Generated test files in test/data (10mb.txt, 100mb.txt)')
