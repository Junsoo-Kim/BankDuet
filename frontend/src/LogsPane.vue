<script setup lang="ts">
import {ref, watch} from 'vue'
import {api,useAction,type Bank,type Trace} from './api'
const props=defineProps<{bank:Bank;tick:number}>()
const sessions=ref<{session_id:string;events:number;updated:string}[]>([]),rows=ref<Trace[]>([]),sid=ref(''),verdict=ref('')
const {act,error}=useAction()
const diagnosis=ref('')
async function sync(){sessions.value=await api(props.bank,'logs');if(sid.value)rows.value=await api(props.bank,'logs/'+sid.value)}
watch(()=>props.tick,()=>sync().catch(()=>{}),{immediate:true})
async function open(id:string){sid.value=id;diagnosis.value='';await sync();const v=await api<{runs:{status:string}[]}>(props.bank,'logs/'+id+'/evaluation');verdict.value=v.runs.map(x=>x.status).join(' · ')}
async function diagnose(){
 const {runs}=await api<{runs:{status:string;warnings:string[];diagnosis:{state:string;text?:string}}[]}>(props.bank,'logs/'+sid.value+'/diagnosis','POST')
 diagnosis.value=runs.filter(r=>r.status==='이상').map(r=>r.warnings.join(', ')+' · '+(r.diagnosis.text??'모델 진단을 사용할 수 없어 규칙 판정을 표시합니다.')).join('\n')
}
</script>
<template><h1>실행 로그</h1><p v-if="!sessions.length">상담을 실행하면 세션별 기록이 표시됩니다.</p><div class="sheet" v-for="s in sessions" :key="s.session_id"><div class="row"><span>{{new Date(s.updated).toLocaleString('ko-KR')}} · 이벤트 {{s.events}}개</span><button class="quiet" @click="act(()=>open(s.session_id))">상세</button></div></div>
<div v-if="sid" class="sheet"><h2>실행 순서</h2><p>규칙 판정 · {{verdict}}</p><button v-if="verdict.includes('이상')" class="quiet" @click="act(diagnose)">이상 원인 진단</button><p v-if="diagnosis">{{diagnosis}}</p><ol><li v-for="t in rows" :key="t.seq"><strong>{{t.kind}}</strong><pre>{{JSON.stringify(t.payload,null,2)}}</pre></li></ol><button class="quiet" @click="act(async()=>{await api(bank,'logs/'+sid,'DELETE');sid='';await sync()})">이 세션 로그 삭제</button></div><p role="alert">{{error}}</p></template>
