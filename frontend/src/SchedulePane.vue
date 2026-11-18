<script setup lang="ts">
import {ref,watch} from 'vue'
import {api,useAction,type Appointment,type Bank} from './api'
const props=defineProps<{bank:Bank;tick:number}>()
const items=ref<Appointment[]>([]),title=ref('은행 상담 준비'),start=ref(''),end=ref(''),id=ref(''),notice=ref('')
const {act,pending,error}=useAction()
async function sync(){items.value=await api(props.bank,'appointments')}
watch(()=>props.tick,()=>sync().catch(()=>{}),{immediate:true})
function local(s:string){const d=new Date(s);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16)}
function edit(a:Appointment){id.value=a.id;title.value=a.title;start.value=local(a.starts_at);end.value=local(a.ends_at)}
function save(){return act(async()=>{
 const r=await api<{conflicts:Appointment[]}>(props.bank,'appointments'+(id.value?'/'+id.value:''),id.value?'PUT':'POST',
 {title:title.value,starts_at:new Date(start.value).toISOString(),ends_at:new Date(end.value).toISOString()})
 notice.value=r.conflicts.length?'저장했습니다. 겹치는 일정 · '+r.conflicts.map(c=>c.title).join(', '):'일정을 저장했습니다.'
 id.value='';await sync()
})}
</script>
<template><h1>상담 준비 일정</h1><p>내 은행에 보관하는 개인 일정입니다.</p><form class="sheet" @submit.prevent="save">
<label>일정 이름<input v-model="title" maxlength="100" required></label><div class="fields"><label>시작<input v-model="start" type="datetime-local" required></label><label>종료<input v-model="end" type="datetime-local" required></label></div><button :disabled="pending">{{id?'수정 저장':'일정 저장'}}</button><button v-if="id" type="button" class="quiet" @click="id=''">취소</button></form>
<p role="status">{{notice}}</p><p role="alert">{{error}}</p><article v-for="a in items" :key="a.id" class="sheet"><h2>{{a.title}}</h2><p>{{new Date(a.starts_at).toLocaleString('ko-KR')}} – {{new Date(a.ends_at).toLocaleTimeString('ko-KR')}}</p>
<div class="actions"><button class="quiet" @click="edit(a)">수정</button><button class="quiet" @click="act(async()=>{await api(bank,'appointments/'+a.id,'DELETE');await sync()})">삭제</button></div></article></template>
