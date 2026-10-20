import '@angular/compiler';
import { HttpHeaders, HttpParams, HttpRequest } from '@angular/common/http';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = path => readFileSync(join(root, path), 'utf8');

// Evaluate the real TypeScript modules with each build's environment.
function moduleFrom(path, dependencies = {}) {
  const code = ts.transpileModule(read(path), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, {
    exports,
    require: name => {
      assert.ok(name in dependencies, `Unexpected runtime dependency: ${name}`);
      return dependencies[name];
    }
  }, { filename: path });
  return exports;
}

function routing(production) {
  const environment = moduleFrom(`src/environments/environment${production ? '.production' : ''}.ts`);
  const urls = moduleFrom('src/app/backend-url.ts', { '../environments/environment': environment });
  const interceptor = moduleFrom('src/app/backend.interceptor.ts', { './backend-url': urls }).backendInterceptor;
  return { ...urls, interceptor };
}

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(item => {
    const path = join(directory, item.name);
    return item.isDirectory() ? sourceFiles(path) : /\.(ts|html)$/.test(path) ? [path] : [];
  });
}

const origin = 'https://traders-gita-api.onrender.com';

test('production routes every API path used by the frontend to Render', () => {
  const { interceptor } = routing(true);
  const paths = new Set();
  for (const file of sourceFiles(join(root, 'src'))) {
    for (const match of readFileSync(file, 'utf8').matchAll(/['"`](\/api\/[^'"`\s]*)/g)) {
      paths.add(match[1]);
    }
  }
  assert.ok(paths.size >= 20);
  for (const path of paths) {
    const request = new HttpRequest('GET', path);
    interceptor(request, rewritten => {
      assert.equal(rewritten.url, origin + path);
      return null;
    });
  }
});

test('interceptor preserves method, body, query parameters, headers and credentials', () => {
  const request = new HttpRequest('POST', '/api/watchlists', { name: 'My stocks' }, {
    params: new HttpParams().set('key', 'NSE_EQ|INE002A01018'),
    headers: new HttpHeaders({ 'X-Test': 'preserved' }), withCredentials: true
  });
  routing(true).interceptor(request, rewritten => {
    assert.equal(rewritten.method, request.method);
    assert.equal(rewritten.body, request.body);
    assert.equal(rewritten.headers, request.headers);
    assert.equal(rewritten.params, request.params);
    assert.equal(rewritten.withCredentials, true);
    assert.equal(rewritten.urlWithParams, origin + request.urlWithParams);
    return null;
  });
});

test('development keeps requests and login navigation on the local proxy', () => {
  const { interceptor, backendUrl } = routing(false);
  for (const path of ['/api/status', '/api/journal/trades', '/auth/upstox', '/oauth/callback']) {
    const request = new HttpRequest('GET', path);
    interceptor(request, rewritten => { assert.equal(rewritten, request); return null; });
    assert.equal(backendUrl(path), path);
  }
});

test('production login links use Render; external URLs and assets are unchanged', () => {
  const { backendUrl, resolveBackendUrl } = routing(true);
  assert.equal(backendUrl('/auth/upstox'), origin + '/auth/upstox');
  assert.equal(backendUrl('api/status?test=1'), origin + '/api/status?test=1');
  assert.equal(resolveBackendUrl('/api/status', origin + '/'), origin + '/api/status');
  for (const url of ['https://example.com/api/status', origin + '/api/status',
    '//example.com/api/status', '/assets/icon.svg', '/api-other', '/']) {
    assert.equal(backendUrl(url), url);
  }
});

test('bootstrap, file replacement and templates use the centralized configuration', () => {
  assert.match(read('src/main.ts'), /provideHttpClient\(withInterceptors\(\[backendInterceptor\]\)\)/);
  const config = JSON.parse(read('angular.json')).projects['market-desk'].architect;
  assert.equal(config.build.defaultConfiguration, 'production');
  assert.equal(config.serve.defaultConfiguration, 'development');
  assert.ok(config.build.configurations.production.fileReplacements.some(
    item => item.replace === 'src/environments/environment.ts' &&
            item.with === 'src/environments/environment.production.ts'));
  assert.equal(JSON.parse(read('proxy.conf.json'))['/api'].target, 'http://localhost:8000');
  for (const file of sourceFiles(join(root, 'src/app'))) {
    const source = readFileSync(file, 'utf8');
    assert.doesNotMatch(source, /https:\/\/traders-gita-api\.onrender\.com/);
    assert.doesNotMatch(source, /href=["']\/(?:api|auth|oauth)\//);
    if (file.endsWith('.html') && source.includes('[href]="loginUrl"')) {
      assert.match(readFileSync(join(dirname(file), file.split(/[\\/]/).pop().replace('.html', '.ts')), 'utf8'),
        /loginUrl = backendUrl\('\/auth\/upstox'\)/);
    }
  }
});
