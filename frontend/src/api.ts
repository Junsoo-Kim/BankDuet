import { ref } from 'vue'

export type Bank = 'kb'|'b'
export type Forecast = {
  capital:number; monthly:number; projected:number; gap:number; needed_months:number|null
  achieve_date:string|null; target_date:string; extra_monthly:number|null; remaining_cycles:number
  milestones:{month:number;amount:number;progress_pct:number}[]
}
export type Plan = {
  id:string; title:string; start:string; target:number; months:number; version:number; owner:Bank
  status:string; created_at:string; votes:Record<string,string>
  shares:Record<string,{capital:number;monthly:number;expires:string}>
  confirmed:{version:number;date:string;months:number;target:number;forecast:Forecast}|null
  history?:{version:number;date:string;months:number;target:number}[]
  forecast:Forecast|null
  private:{balance:number;reserve:number;monthly:number;consent:string;expires:string|null;as_of?:string;
    savings_history?:{date:string;amount:number;type:string}[];
    expenses:Record<string,{amount:number;note:string;posted:boolean}>}
}
export type Run = {id:string;prompt:string;state:string;answer:string|null}
export type Trace = {seq:number;run_id:string;kind:string;payload:Record<string,unknown>}
export type Appointment = {id:string;title:string;starts_at:string;ends_at:string}

export function money(n:number) {return n.toLocaleString('ko-KR')+'원'}
export const labels:Record<string,string> = {invited:'상대 참여 대기',review:'양측 검토 중',confirmed:'확정',rejected:'거절됨'}
export const banks = {kb:'KB국민은행',b:'B은행'}
export async function api<T>(bank:string,path:string,method='GET',body?:unknown):Promise<T> {
  const response=await fetch('/'+bank+'/api/'+path,{method,headers:{'Content-Type':'application/json'},
    body:body===undefined?undefined:JSON.stringify(body)})
  if(!response.ok){
    const data=await response.json().catch(()=>({}))
    throw new Error(typeof data.detail==='string'?data.detail:'요청을 처리할 수 없습니다. 입력과 은행 연결을 확인하세요.')
  }
  return response.json()
}
export function useAction(){
  const error=ref(''),pending=ref(false)
  async function act(fn:()=>Promise<void>){
    if(pending.value)return
    pending.value=true;error.value=''
    try{await fn()}catch(e){error.value=e instanceof Error?e.message:'요청 실패'}finally{pending.value=false}
  }
  return {act,pending,error}
}
