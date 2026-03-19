const { pathToFileURL } = require('url');
const path = require('path');
process.chdir(__dirname);
process.argv.push('--port', '5173');
import(pathToFileURL(path.join(__dirname, 'node_modules', 'vite', 'bin', 'vite.js')).href);
