<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
import {RouterLink,useRoute} from 'vue-router'
import PlansPane from './PlansPane.vue'
import ChatPane from './ChatPane.vue'
import SchedulePane from './SchedulePane.vue'
import LogsPane from './LogsPane.vue'
import {api,banks,type Bank,type Plan} from './api'
const props=defineProps<{bank:Bank}>()
const route=useRoute()
const sections=[['plans','공동 목표'],['chat','계획 상담'],['schedule','상담 일정'],['logs','실행 로그']]
const section=computed(()=>String(route.params.section||'plans'))
const plans=ref<Plan[]>([]),id=ref(localStorage.getItem('goal-'+props.bank)??''),tick=ref(0)
const chosen=computed(()=>plans.value.find(p=>p.id===id.value)??plans.value[0]??null)
const status=ref('연결 중'),customer=ref(''),error=ref(''),connected=ref(false)
let source:EventSource|undefined,closed=false, refreshing=false, again=false
let updateTimer:ReturnType<typeof setTimeout>|undefined
function select(idValue:string){id.value=idValue;localStorage.setItem('goal-'+props.bank,idValue)}
async function refresh(){
 if(refreshing){again=true;return}
 refreshing=true
 try{do{again=false;plans.value=await api(props.bank,'plans')}while(again&&!closed)}
 catch{error.value='은행 데이터를 불러오지 못했습니다.'}finally{refreshing=false}
}
async function connect(){
 source?.close();error.value=''
 try{
 const session=await api<{customer:string}>(props.bank,'session','POST')
 customer.value=session.customer
 const {cursor}=await api<{cursor:number}>(props.bank,'events/cursor')
 if(closed)return
 source=new EventSource('/'+props.bank+'/api/events?after='+cursor)
 source.onopen=()=>{status.value='실시간 연결';connected.value=true;void refresh();tick.value++}
 source.onerror=()=>{status.value='재연결 중';connected.value=false}
 source.onmessage=e=>{const event=JSON.parse(e.data);if(event.kind==='plan')void refresh()
 if(!updateTimer)updateTimer=setTimeout(()=>{tick.value++;updateTimer=undefined},100)}
 await refresh()
 }catch{error.value='은행 연결을 확인해 주세요.';status.value='연결 대기'}
}
onMounted(()=>{window.addEventListener('online',connect);void connect()})
onBeforeUnmount(()=>{closed=true;window.removeEventListener('online',connect);source?.close();clearTimeout(updateTimer)})
</script>
<template><header class="top"><div class="wrap topbar"><b class="wordmark">BankDuet</b><div class="banknav"><RouterLink to="/kb/">KB국민은행</RouterLink><RouterLink to="/b/">B은행</RouterLink></div></div></header>
<div class="wrap shell"><aside><strong>{{banks[bank]}}</strong><p>가상 고객 · {{customer}}</p><nav><RouterLink v-for="[slug,label] in sections" :key="slug" :class="{active:section===slug}" :to="'/'+bank+'/'+slug">{{label}}</RouterLink></nav><small><i class="dot" :class="{online:connected}"></i>{{status}}</small></aside>
<main><p v-if="error" class="error">{{error}} <button @click="connect">다시 연결</button></p>
<PlansPane v-if="section==='plans'" :bank="bank" :plans="plans" :active="chosen" @select="select" @refresh="refresh"/>
<ChatPane v-else-if="section==='chat' && customer" :bank="bank" :active="chosen" :tick="tick"/>
<SchedulePane v-else-if="section==='schedule' && customer" :bank="bank" :tick="tick"/>
<LogsPane v-else-if="section==='logs' && customer" :bank="bank" :tick="tick"/>
</main></div></template>
<style>
*{box-sizing:border-box}body{margin:0;background:#f7f6f1;color:#162f2a;font-family:Inter,"Malgun Gothic",sans-serif;line-height:1.55}
.wrap{max-width:1160px;margin:auto;padding:0 28px}.top{background:#123d34;color:white}.topbar,.section-head,.row,.spread{display:flex;align-items:center;justify-content:space-between;gap:16px}.topbar{min-height:70px}
.wordmark{font-size:26px;letter-spacing:-1px}.banknav{display:flex;gap:16px}.banknav a{color:white}.shell{display:grid;grid-template-columns:185px 1fr;gap:48px;padding-top:36px;padding-bottom:70px}
aside{border-right:1px solid #d6dfd7}aside p,.spread,small,.picker,.metrics span{font-size:14px;color:#51655e}nav{display:grid;gap:5px;margin:26px 15px 28px 0}
nav a{text-decoration:none;color:#38544a;padding:9px 14px;border-radius:8px}nav .active{background:#dfeae3;font-weight:700;color:#113d30}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#a38140;margin-right:8px}.online{background:#2c7d59}
main{min-width:0}h1{font-size:clamp(28px,4vw,40px);letter-spacing:-2px;margin:0 0 18px}h2{font-size:21px;margin:0 0 12px}.eyebrow{color:#567363;font-size:14px;margin:0}.hero{padding:28px 32px;background:#17493e;color:#fff;border-radius:16px}.hero p{color:#deece1}.target{font-size:clamp(28px,4vw,46px);font-weight:700;letter-spacing:-1.5px}.metrics,.fields,.actions{display:flex;gap:12px;flex-wrap:wrap}.metrics{margin:16px 0}.metrics div,.sheet{background:#fff;border:1px solid #d9e0d9;border-radius:13px;padding:20px}.metrics div{flex:1;min-width:145px}.metrics strong,.metrics span{display:block}.sheet{margin:14px 0}.fields label{flex:1;min-width:135px}label{display:grid;gap:5px;margin:8px 0 14px;font-size:14px}input,select,textarea{font:inherit;border:1px solid #a8b7af;border-radius:6px;padding:9px;background:#fff;color:#15372d;max-width:100%}textarea{min-height:65px}.check{display:flex;align-items:center}.picker{max-width:400px}.actions{align-items:center}
button{font:inherit;background:#1c5647;color:#fff;border:1px solid transparent;border-radius:7px;padding:8px 14px;cursor:pointer}button.quiet{background:#edf2eb;color:#224a3d;border-color:#d6dfd7}button:disabled{opacity:.5;cursor:default}.error{color:#912b22}.bars{display:flex;align-items:flex-end;height:95px;gap:4px}.column{height:100%;flex:1;display:flex;align-items:flex-end}.column i{background:#6caa8d;width:100%;border-radius:4px 4px 0 0}.column:last-child i{background:#195641}.spread{margin-top:6px}.row{border-bottom:1px solid #e6e9e2;padding:10px 0}summary{cursor:pointer;color:#416556;margin:12px 0}.answer,pre{white-space:pre-wrap;overflow-wrap:anywhere}li{margin:4px 0}a{color:#205b4d}
@media(max-width:760px){.wrap{padding-left:16px;padding-right:16px}.shell{display:block;padding-top:14px}aside{border:0}aside p,aside small{display:inline-block;margin:0 8px}nav{display:flex;flex-wrap:wrap;margin:8px 0 18px}nav a{padding:5px 9px}.section-head{align-items:flex-start}.hero{padding:20px}.metrics{gap:6px}.metrics div{padding:10px;min-width:110px}}
</style>
