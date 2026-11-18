import { test, expect, signIn } from './fixtures';
import { execFileSync } from 'node:child_process';

test('protected page redirects without a session and after session expiry', async ({page, context}) => {
  // Direct navigation is intentional: this is the protected-route boundary.
  const me = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/me' && r.status() === 401);
  await page.goto('/suppliers');
  expect((await me).status()).toBe(401);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('button',{name:'Sign in'})).toBeVisible();
  await signIn(page,'analyst@procurem.demo');
  const token = (await context.cookies()).find(cookie => cookie.name === 'procurem_session')?.value;
  expect(token).toBeTruthy();
  // Expire this exact session in the run's isolated SQLite file, not all sessions.
  execFileSync(process.env.E2E_PYTHON!, ['-c', 'import hashlib,sqlite3,sys; db=sqlite3.connect(sys.argv[1]); c=db.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?", ("2000-01-01T00:00:00+00:00",hashlib.sha256(sys.argv[2].encode()).hexdigest())); db.commit(); assert c.rowcount == 1', process.env.E2E_DATABASE_PATH!, token!]);
  const expired = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/me' && r.status() === 401);
  await page.getByRole('link',{name:'Suppliers',exact:true}).first().click();
  expect((await expired).status()).toBe(401);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('button',{name:'Sign in'})).toBeVisible();
});

test('restricted knowledge detail is hidden from analyst on direct URL', async ({page, context}) => {
  // Establish the browser's authenticated cookie before its first navigation.
  const login = await context.request.post('/api/v1/auth/login', {data:{email:'analyst@procurem.demo',password:'Demo@1234'}});
  expect(login.status()).toBe(200);
  expect((await login.json()).role).toBe('analyst');
  const identity = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/auth/me');
  const denied = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/knowledge/5');
  await page.goto('/knowledge/5'); // Deliberate initial direct-URL authorization probe.
  const me = await identity;
  expect(me.status()).toBe(200);
  expect((await me.json()).role).toBe('analyst');
  expect((await denied).status()).toBe(404);
  await expect(page.getByText('Record not found.')).toBeVisible();
});

test('hostile requisition markup is rejected and user-supplied text remains inert in the assistant', async ({page, context}) => {
  await page.addInitScript(() => { (window as unknown as {xssExecuted: number}).xssExecuted = 0; });
  await page.goto('/');
  await signIn(page,'analyst@procurem.demo');
  const payload = `<img src=x onerror="window.xssExecuted=1"><script>window.xssExecuted=2</script>`;
  const draft = await context.request.post('/api/v1/requisitions', {data:{supplier_id:1,title:payload,reason:'Browser security test',lines:[{description:'Safety test',quantity:1,unit_price:'1.00'}]}});
  expect(draft.status()).toBe(422);

  // Benign special characters remain valid free text and exercise output encoding.
  const safeText = 'Safety check: R&D < 2 > 1';
  await page.getByRole('link',{name:'Assistant',exact:true}).click();
  const input = page.getByLabel('Ask the assistant');
  await input.fill(safeText);
  const sent = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/assistant/messages' && r.request().method() === 'POST');
  await input.press('Enter');
  const response = await sent;
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(result.conversation_id).toBeTruthy();
  const message = page.getByRole('region',{name:'Assistant conversation'}).getByText(safeText,{exact:true});
  await expect(message).toBeVisible();
  await expect(message.locator('img, script')).toHaveCount(0);
  expect(await message.innerHTML()).toContain('&lt;');
  expect(await message.innerHTML()).toContain('&amp;');
  await expect(page.getByText(result.answer.text,{exact:true})).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as {xssExecuted:number}).xssExecuted)).toBe(0);
});

test('hostile assistant message is rejected without saving a turn', async ({page, context}) => {
  await page.addInitScript(() => { (window as unknown as {xssExecuted:number}).xssExecuted = 0; });
  await page.goto('/');
  await signIn(page,'analyst@procurem.demo');
  await page.getByRole('link',{name:'Assistant',exact:true}).click();
  const input = page.getByLabel('Ask the assistant');
  const title = `Show overdue purchase orders security ${Date.now()}`;
  await input.fill(title);
  const initialResponse = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/assistant/messages' && r.request().method() === 'POST');
  await input.press('Enter');
  const initial = await initialResponse;
  expect(initial.status()).toBe(200);
  const result = await initial.json();
  await expect(page.getByRole('link',{name:result.answer.sections[0].rows[0].code,exact:true})).toBeVisible();
  const historyUrl = `/api/v1/assistant/conversations/${result.conversation_id}`;
  const beforeResponse = await context.request.get(historyUrl);
  expect(beforeResponse.status()).toBe(200);
  const before = await beforeResponse.json();
  expect(before.messages).toHaveLength(2);
  const payload = '<img src=x onerror="window.xssExecuted=1"><script>window.xssExecuted=2</script>';
  // APIRequestContext sends the hostile turn without injecting markup into the DOM.
  const rejected = await context.request.post('/api/v1/assistant/messages',{data:{message:payload,conversation_id:result.conversation_id}});
  expect(rejected.status()).toBe(422);
  const afterResponse = await context.request.get(historyUrl);
  expect(afterResponse.status()).toBe(200);
  expect((await afterResponse.json()).messages).toEqual(before.messages);
  await page.getByRole('button',{name:'New',exact:true}).click();
  await page.getByRole('button',{name:title,exact:true}).click();
  await expect(page.getByText(payload,{exact:true})).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as {xssExecuted:number}).xssExecuted)).toBe(0);
});
