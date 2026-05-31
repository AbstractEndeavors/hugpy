import path from 'node:path'
import { fileURLToPath } from 'node:url'
import HtmlWebpackPlugin from 'html-webpack-plugin'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

export default {
  entry: './src/main.jsx',

  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'assets/[name].[contenthash].js',
    clean: true,
    publicPath: '/',
  },

  resolve: {
    extensions: ['.js', '.jsx', '.ts', '.tsx'],
    fallback: {
      util: false,        // stub out Node's util; the auth path doesn't need it in-browser
    },
  },
  devServer: {
  host: '127.0.0.1',
  port: 6091,
  allowedHosts: ['dev.abstractgpt.ai'],   // or 'all' for dev
  // HMR over nginx's TLS — tell the client to reach the socket via wss:443
  client: {
    webSocketURL: 'wss://dev.abstractgpt.ai:443/ws',
  },
  // proxy /api to prod
  proxy: [
    {
      context: ['/api'],
      target: 'https://abstractgpt.ai',
      changeOrigin: true,
      secure: true,
    },
  ],
  historyApiFallback: true,   // SPA routing
},
  module: {
    rules: [
      {
        test: /\.(js|jsx|ts|tsx)$/,
        exclude: /node_modules/,
        use: {
          loader: 'babel-loader',
          options: {
            presets: [
              ['@babel/preset-env', { targets: 'defaults' }],
              ['@babel/preset-react', { runtime: 'automatic' }],
              '@babel/preset-typescript',
            ],
          },
        },
      },
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader'],
      },
    ],
  },

  plugins: [
    new HtmlWebpackPlugin({
      template: './index.html',
    }),
  ],

}
