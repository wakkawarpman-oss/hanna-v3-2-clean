'use strict'

const { buildOptimizedApp } = require('./app-opt')
const { ParserPool } = require('./components/parser-pool')

async function start () {
  const parserPool = new ParserPool(4)
  const app = await buildOptimizedApp({ logger: true, lazyRoutes: true })

  app.decorate('parserPool', parserPool)

  app.addHook('onClose', async () => {
    await parserPool.destroy()
  })

  await app.listen({ port: 3000, host: '0.0.0.0' })
  console.log('HANNA worker app listening on port 3000')
}

start().catch((err) => {
  console.error(err)
  process.exit(1)
})
