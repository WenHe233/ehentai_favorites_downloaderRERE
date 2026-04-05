import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }

          if (id.includes('@ant-design/icons')) {
            return 'antd-icons'
          }

          if (id.includes('antd') || id.includes('@ant-design')) {
            return 'antd'
          }

          if (id.includes('/rc-') || id.includes('@rc-component')) {
            return 'rc-components'
          }

          if (id.includes('react-router')) {
            return 'router'
          }

          if (id.includes('react')) {
            return 'react-vendor'
          }

          if (id.includes('axios')) {
            return 'axios'
          }

          if (id.includes('dayjs')) {
            return 'dayjs'
          }

          return 'vendor'
        },
      },
    },
  },
})
