import { test, expect, signIn } from './fixtures';

test('dashboard metrics and chart open their corresponding live directories', async ({page}) => {
  await page.goto('/');
  const dashboardResponse = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/dashboard');
  await signIn(page, 'analyst@procurem.demo');
  const dashboard = await dashboardResponse;
  expect(dashboard.status()).toBe(200);
  const data = await dashboard.json();
  const entries = [
    {label:/Suppliers.*Real-time/, count:String(data.supplier_count), path:'/suppliers', api:'/api/v1/records/suppliers', query:{}},
    {label:/Open purchase orders.*Real-time/, count:String(data.open_order_count), path:'/purchase-orders?status=open', api:'/api/v1/records/purchase-orders', query:{status:'open'}},
    {label:/Open orders without invoice.*Real-time/, count:String(data.no_invoice_count), path:'/purchase-orders?status=open&no_invoice=true', api:'/api/v1/records/purchase-orders', query:{status:'open',no_invoice:'true'}},
    {label:/Open order total \(USD\).*Real-time/, count:`$${Number(data.open_order_usd).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`, path:'/purchase-orders?status=open', api:'/api/v1/records/purchase-orders', query:{status:'open'}},
    {label:/Pending approvals.*Real-time/, count:String(data.pending_approval_count), path:'/approvals', api:'/api/v1/approvals', query:{}},
  ];
  for (const entry of entries) {
    const metric = page.getByRole('link',{name:entry.label});
    await expect(metric).toHaveAttribute('href',entry.path);
    await expect(metric).toContainText(entry.count);
    const list = page.waitForResponse(r => {
      const url = new URL(r.url());
      return url.pathname === entry.api && Object.entries(entry.query).every(([key,value]) => url.searchParams.get(key) === value);
    });
    await metric.click();
    const response = await list;
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(Array.isArray(result.items)).toBe(true);
    await expect(page).toHaveURL(new RegExp(`${entry.path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`));
    if (entry.query.status) expect(result.items.every((item: {status:string}) => item.status === 'open')).toBe(true);
    if ('no_invoice' in entry.query) expect(result.items.every((item: {has_invoice:number}) => !item.has_invoice)).toBe(true);
    if (result.items.length) {
      const code = result.items[0].code ?? result.items[0].title;
      await expect(page.getByRole('link',{name:code,exact:true}).first()).toBeVisible();
    } else {
      await expect(page.getByText('No records match these filters.')).toBeVisible();
    }
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Home',exact:true}).click();
  }
  const sidebarInbox = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/approvals');
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Approvals',exact:true}).click();
  const inboxResponse = await sidebarInbox;
  expect(inboxResponse.status()).toBe(200);
  const inbox = await inboxResponse.json();
  expect(inbox.items.length).toBeGreaterThan(0);
  await expect(page.getByRole('link',{name:inbox.items[0].title,exact:true})).toBeVisible();
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Home',exact:true}).click();
  const spend = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/records/spend');
  await page.getByRole('link',{name:'View spend by category'}).click();
  const response = await spend;
  expect(response.status()).toBe(200);
  const items = (await response.json()).items;
  expect(items.length).toBeGreaterThan(0);
  await expect(page.getByRole('link',{name:items[0].category,exact:true}).first()).toBeVisible();
});
