<script setup lang="ts">
import {ref,computed,watch} from 'vue'
import {api,banks,labels,money,useAction,type Bank,type Plan} from './api'
const props=defineProps<{bank:Bank;plans:Plan[];active:Plan|null}>()
const emit=defineEmits<{select:[id:string];refresh:[]}>()
const {act,pending,error}=useAction()
const name=ref('신혼집 자기자금'), target=ref(1000000000), months=ref(120),mode=ref('auto'), form=ref(false)
const expense=ref(10000000),note=ref('예정 지출'), missedMonth=ref(1), panel=ref(''), consent=ref(false)
const reserve=ref(5000000),monthly=ref(2500000)
const depositAmount=ref(2500000)
const editing=ref(false),notice=ref('')
const p=computed(()=>props.active), f=computed(()=>p.value?.forecast)
watch(()=>p.value?.id,()=>{panel.value='';notice.value='';editing.value=false})
watch(()=>[p.value?.private.reserve,p.value?.private.monthly],()=>{
 if(p.value){reserve.value=p.value.private.reserve;monthly.value=p.value.private.monthly}
},{immediate:true})
function edit(){
  if(!p.value)return
  name.value=p.value.title;target.value=p.value.target;months.value=p.value.months
  editing.value=true;form.value=true
}
function start(){
  editing.value=false;form.value=true;consent.value=false
  name.value='신혼집 자기자금';target.value=1000000000;months.value=120
}
function save(){
  return act(async()=>{
    let row:Plan
    if(editing.value && p.value){
      row=await api(props.bank,'plans/'+p.value.id,'PUT',{title:name.value,target:target.value,months:months.value,version:p.value.version})
    }else{
      if(!consent.value)throw new Error('기여액 공유 범위를 확인해 주세요.')
      row=await api(props.bank,'plans','POST',{title:name.value,target:target.value,months:months.value,mode:mode.value})
    }
    form.value=false;emit('select',row.id);emit('refresh')
  })
}
function send(path:string,body?:unknown,method='POST'){
  return act(async()=>{
    if(!p.value)return
    await api(props.bank,'plans/'+p.value.id+path,method,body)
    notice.value='요청을 반영했습니다. 타행 응답은 도착하면 표시됩니다.'
    emit('refresh')
  })
}
function addExpense(){return send('/expenses',{id:crypto.randomUUID(),amount:expense.value,note:note.value})}
</script>
<template>
<section class="section-head"><div><p class="eyebrow">공동 금융목표</p><h1>우리의 자금 계획</h1></div><button @click="start">목표 만들기</button></section>
<p v-if="error" class="error" role="alert">{{error}}</p>
<form v-if="form" class="sheet" @submit.prevent="save">
  <h2>{{editing?'수정안 작성':'새 공동 목표'}}</h2>
  <div class="fields"><label>목표 이름<input v-model="name" required maxlength="80"></label>
  <label>자기자금 목표 (원)<input type="number" min="1" v-model.number="target" required></label>
  <label>납입 기간 (개월)<input type="number" min="1" max="600" v-model.number="months" required></label></div>
  <template v-if="!editing"><label>기여액 공유 범위<select v-model="mode"><option value="auto">30일간 변경값 자동 공유</option><option value="once">최초 한 번만 공유</option></select></label>
  <label class="check"><input type="checkbox" v-model="consent" required> 상대 은행에 목표 기여액과 납입 조건을 공유합니다.</label></template>
  <div class="actions"><button :disabled="pending">저장</button><button type="button" class="quiet" @click="form=false">취소</button></div>
</form>
<template v-if="plans.length">
<label class="picker">조회할 목표<select :value="p?.id" @change="emit('select',($event.target as HTMLSelectElement).value)"><option v-for="g in plans" :key="g.id" :value="g.id">{{g.title}}</option></select></label>
<template v-if="p"><article class="hero"><p>{{banks[p.owner]}} 개설 · 제안 v{{p.version}} · {{labels[p.status]}}</p><h2>{{p.title}}</h2><div class="target">{{money(p.target)}}</div><p>{{p.start}}부터 {{p.months}}개월 · 원금 기준</p></article>
<div v-if="f" class="metrics"><div><span>목표일 예상액</span><strong>{{money(f.projected)}}</strong></div><div><span>부족액</span><strong>{{money(f.gap)}}</strong></div><div><span>예상 달성일</span><strong>{{f.achieve_date??'산정 보류'}}</strong></div></div>
<div v-if="f" class="sheet"><h2>원금 적립 경로</h2><div class="bars" role="img" :aria-label="'초기 '+money(f.capital)+'에서 '+money(f.projected)">
<div v-for="m in f.milestones" :key="m.month" class="column" :title="m.month+'개월 '+money(m.amount)+' · '+m.progress_pct+'%'"><i :style="{height:Math.max(2, m.amount/Math.max(p.target,f.projected,1)*100)+'%'}"></i></div></div>
<div class="spread"><span>시작 · {{money(f.capital)}}</span><span>{{p.months}}개월 · {{money(f.projected)}}</span></div>
<p v-if="f.gap">{{f.needed_months===null?'현재 납입 조건으로 달성일을 산정할 수 없습니다.':'월 한도를 유지하면 '+f.needed_months+'개월이 필요합니다.'}} <template v-if="f.extra_monthly!=null">남은 {{f.remaining_cycles}}회 동안 월 합산 {{money(f.extra_monthly)}}을 더 모으면 목표일을 유지할 수 있습니다.</template><template v-else>남은 납입 회차가 없어 목표일 조정이 필요합니다.</template></p></div>
<p v-else class="sheet">양쪽 기여액이 공유되면 공동 예상액을 계산합니다.</p>
<div class="sheet"><h2>동의와 승인</h2>
<p v-for="(snap,bankKey) in p.shares" :key="bankKey">{{banks[bankKey as Bank]}} · 초기 기여 {{money(snap.capital)}} · 월 {{money(snap.monthly)}} · 공유 기한 {{new Date(snap.expires).toLocaleDateString('ko-KR')}} {{Date.parse(snap.expires)<=Date.now()?'(만료 · 재동의 필요)':''}}</p>
<p>현재 공유 설정 · {{({none:'초대 수락 전',once:'최초 한 번',auto:'변경값 자동 공유',revoked:'철회'} as Record<string,string>)[p.private.consent]}}</p>
<div class="actions"><button class="quiet" @click="send('/consent',{mode:'once'})">한 번 공유</button><button class="quiet" @click="send('/consent',{mode:'auto'})">변경값 자동 공유</button><button v-if="p.private.consent!=='none'" class="quiet" @click="send('/consent',{mode:'revoked'})">동의 철회</button></div>
<p v-if="p.confirmed">마지막 확정 · v{{p.confirmed.version}} · {{money(p.confirmed.target)}} · {{p.confirmed.date}}</p>
<details v-if="p.history?.length"><summary>확정 이력</summary><ul><li v-for="v in p.history" :key="v.version">v{{v.version}} · {{v.months}}개월 · {{v.date}} · {{money(v.target)}}</li></ul></details>
<p v-if="p.status==='review'">KB {{p.votes.kb==='approve'?'승인':'대기'}} · B은행 {{p.votes.b==='approve'?'승인':'대기'}}</p>
<div v-if="p.status==='review'" class="actions"><button :disabled="pending||!!f?.gap" @click="send('/versions/'+p.version+'/decisions',{choice:'approve'})">v{{p.version}} 승인</button>
<button v-if="f?.gap" @click="send('/versions/'+p.version+'/decisions',{choice:'extend'})">월 한도 유지 · 기간 연장 제안</button>
<button class="quiet" @click="send('/versions/'+p.version+'/decisions',{choice:'reject'})">거절</button></div></div>
<div class="sheet"><h2>내 은행 자금 변동</h2><p>모킹 잔액 {{money(p.private.balance)}} · 비상금 {{money(p.private.reserve)}} · 월 납입 {{money(p.private.monthly)}}</p>
<details v-if="p.private.savings_history"><summary>월 납입액의 근거 · 최근 3개월 저축 이력</summary><p>가상 원장의 직전 3개월 저축 이체 평균을 최초 제안에 사용했습니다.</p><ul><li v-for="entry in p.private.savings_history" :key="entry.date">{{entry.date}} · {{entry.type}} · {{money(entry.amount)}}</li></ul><p v-if="p.private.as_of">잔액 기준 · {{new Date(p.private.as_of).toLocaleString('ko-KR')}}</p></details>
<details><summary>비상금과 월 납입 계획 수정</summary><div class="fields"><label>비상금 (원)<input v-model.number="reserve" type="number" min="0"></label><label>월 납입 (원)<input v-model.number="monthly" type="number" min="0"></label></div><button class="quiet" @click="send('/budget',{reserve,monthly},'PUT')">내 납입 조건 저장</button></details>
<div class="fields"><label>예정 지출 (원)<input v-model.number="expense" type="number" min="1"></label><label>내 은행에 남길 사유<input v-model="note" maxlength="120"></label></div>
<button :disabled="pending" @click="addExpense">지출 반영</button>
<div v-for="(v,k) in p.private.expenses" :key="k" class="row"><span>{{v.note}} · {{money(v.amount)}}</span><button v-if="!v.posted" class="quiet" @click="send('/expenses/'+k+'/post')">출금 완료 처리</button><span v-else>출금 반영됨</span></div>
<details><summary>회차별 실제 납입 · 누락 기록</summary><div class="fields"><label>납입 회차<input v-model.number="missedMonth" type="number" min="1" :max="p.months"></label><label>실제 납입 (원)<input v-model.number="depositAmount" type="number" min="1"></label></div><div class="actions"><button class="quiet" @click="send('/deposits',{month:missedMonth,amount:depositAmount})">납입 반영</button><button class="quiet" @click="send('/missed',{month:missedMonth})">누락 반영</button></div></details></div>
<div v-if="bank===p.owner" class="actions"><button class="quiet" @click="edit">계획 수정</button><button class="quiet" @click="panel='delete'">목표 삭제</button><button v-if="panel==='delete'" @click="send('',undefined,'DELETE')">양쪽 목록에서 삭제 확인</button></div>
<p role="status">{{notice}}</p>
</template></template>
<div v-else-if="!form" class="sheet"><h2>아직 공동 목표가 없습니다</h2><p>목표를 만들면 상대 은행 화면에 초대가 도착합니다.</p></div>
</template>
