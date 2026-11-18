<script setup lang="ts">
import {ref,watch,computed} from 'vue'
import {api,useAction,type Run,type Trace,type Plan,type Bank} from './api'
const props=defineProps<{bank:Bank;active:Plan|null;tick:number}>()
const key='bankduet-session-'+props.bank
const session=localStorage.getItem(key)??crypto.randomUUID()
localStorage.setItem(key,session)
const runs=ref<Run[]>([]),trace=ref<Trace[]>([]),message=ref(''),{act,error,pending}=useAction()
const busy=computed(()=>pending.value||runs.value.some(r=>r.state==='running'))
async function refresh(){[runs.value,trace.value]=await Promise.all([api<Run[]>(props.bank,'chat/sessions/'+session),api<Trace[]>(props.bank,'logs/'+session)])}
watch(()=>props.tick,()=>refresh().catch(()=>{}),{immediate:true})
function ask(text:string){return act(async()=>{
 await api(props.bank,'chat/runs','POST',{session_id:session,plan_id:props.active?.id??null,message:text})
 message.value='';await refresh()
})}
</script>
<template><div class="section-head"><div><p class="eyebrow">금융 여정 Agent</p><h1>계획 상담</h1></div></div>
<p>현재 목표 · {{active?.title??'선택한 목표 없음'}}</p>
<div v-for="r in runs" :key="r.id" class="sheet"><strong>{{r.prompt}}</strong><p class="answer">{{r.answer??'처리 중…'}}</p>
<details><summary>실행 과정</summary><ol><li v-for="t in trace.filter(x=>x.run_id===r.id)" :key="t.seq">{{t.kind}} · {{t.payload.stage??t.payload.name??t.payload.reason??t.payload.alternative??''}}</li></ol></details></div>
<div class="actions"><button v-for="q in ['내 계좌 잔액은?','월 한도 유지, 기간 연장 허용하면 언제 달성해?','영통에서 상담할 은행 지점','사용법 알려줘']" :key="q" class="quiet" :disabled="busy" @click="ask(q)">{{q}}</button></div>
<form class="sheet" @submit.prevent="ask(message)"><label>질문<textarea v-model="message" maxlength="1000" required></textarea></label><button :disabled="busy">{{busy?'응답 대기 중':'질문 보내기'}}</button></form><p role="alert">{{error}}</p></template>
