import { test, expect, type Page } from '@playwright/test'
const longTitle = '测试.長い标题与中文 ' .repeat(35)
async function setup(page:Page,auth=false) {
 const requests:string[]=[]
 const settings:Record<string,unknown>={eh_domain:'e-hentai.org',download_mode:'archive',archive_quality:'original',max_concurrent_downloads:3,max_retries:3,output_template:'./downloads/[{gid}] {title}.zip',conflict_strategy:'rename',truncate_filenames:true,filename_max_length:160,monitored_favcats:[0,1],fav_date_timezone:'site',auto_sync:false,cookie_auto_refresh:true,ipb_member_id_configured:true,ipb_pass_hash_configured:true,igneous_configured:true,allowed_telegram_ids:[],telegram_notification_recipients:[],telegram_notification_batch_window_seconds:60,telegram_notification_quiet_hours_start:'23:00',telegram_notification_quiet_hours_end:'08:00'}
 const galleries=[{gid:123,token:'example',title:longTitle,status:'failed',filecount:12,error_msg:'旧文件名过长',download_path:null,progress:{phase:'failed',percent:0,detail:'文件名过长',updated_at:'2026-10-02T12:00:00Z'}}]
 await page.route('**/api/v1/**', async route=>{
  const request=route.request(); const path=new URL(request.url()).pathname.replace('/api/v1',''); requests.push(request.method()+' '+path)
  const json=(data:unknown)=>route.fulfill({json:data})
  if(path==='/auth/config')return json({auth_enabled:auth})
  if(path==='/auth/login')return json({access_token:'test-token'})
  if(path==='/auth/me')return json({username:'admin'})
  if(path==='/events/downloads')return route.fulfill({contentType:'text/event-stream',body:'event: snapshot\r\ndata: {"active_galleries":[],"sync_status":{"sync_running":false},"downloader_running":true}\r\n\r\n'})
  if(path==='/status')return json({downloader_running:true,queue_len:3,active_downloads:0,max_concurrent_downloads:3,failed_retry_count:1,last_sync_ts:'2026-10-02 12:00',sync_running:false})
  if(path==='/account')return json({gp:12345,credits:6789})
  if(path==='/settings') {if(request.method()==='POST')Object.assign(settings,request.postDataJSON());return json(settings)}
  if(path==='/maintenance/legacy-state')return json({legacy_app_config_count:0,temp_cookies_exists:false,downloads_zip_exists:false})
  if(path==='/galleries')return json({items:galleries,total:galleries.length})
  if(path.endsWith('/logs'))return json({logs:[{time:'2026-10-02T12:00:00Z',level:'error',msg:'文件名过长，请启用截断后重试'}]})
  return json({status:'ok',msg:'已加入队列'})
 })
 return {requests,settings}
}
test('overview renders and supports dark mode',async({page},testInfo)=>{
 await setup(page);await page.goto('/');await expect(page.getByRole('heading',{name:'收藏与下载',exact:true})).toBeVisible()
 await expect(page.getByText('12,345',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'切换主题'}).click();await page.getByRole('menuitem',{name:'深色',exact:true}).click()
 await expect(page.locator('html')).toHaveClass(/dark/)
 await page.screenshot({path:testInfo.outputPath('overview.png'),fullPage:true})
})
test('long title, logs, resize and retry remain accessible',async({page})=>{
 const {requests}=await setup(page);await page.goto('/galleries')
 await page.getByRole('button',{name:longTitle.trim(),exact:true}).click()
 await expect(page.getByRole('dialog')).toContainText(longTitle.trim())
 await expect(page.getByRole('dialog')).toContainText('启用截断后重试')
 await page.getByRole('button',{name:'按当前设置重试'}).click()
 await expect.poll(()=>requests.includes('POST /galleries/123/reset')).toBeTruthy()
})
test('settings save the new filename limit and cookie refresh uses one API prefix',async({page})=>{
 const {requests,settings}=await setup(page);await page.goto('/settings')
 await page.getByRole('tab',{name:'下载',exact:true}).click()
 await page.getByLabel('文件名最大长度',{exact:true}).fill('80')
 await page.getByRole('button',{name:'保存设置',exact:true}).last().click()
 await expect.poll(()=>settings.filename_max_length).toBe(80)
 await page.getByRole('tab',{name:'账号',exact:true}).click()
 await page.getByRole('button',{name:'立即刷新 Igneous'}).click()
 await expect.poll(()=>requests.includes('POST /auth/eh-refresh-igneous')).toBeTruthy()
 expect(requests.some(value=>value.includes('/api/v1/auth'))).toBeFalsy()
})
test('authenticated installation opens the login page first',async({page})=>{
 await setup(page,true);await page.goto('/')
 await page.getByLabel('用户名',{exact:true}).fill('admin');await page.getByLabel('密码',{exact:true}).fill('test-password')
 await page.getByRole('button',{name:'登录',exact:true}).click()
 await expect(page.getByRole('heading',{name:'收藏与下载',exact:true})).toBeVisible()
})
