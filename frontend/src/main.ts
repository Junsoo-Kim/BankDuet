import { createApp, h } from 'vue'
import { createRouter, createWebHistory, RouterView, useRoute } from 'vue-router'
import BankView from './BankView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/kb/' },
    { path: '/:bank(kb|b)/:section(plans|chat|schedule|logs)?', component: BankView, props: r=>({bank:r.params.bank}) },
  ],
})
createApp({ setup(){const route=useRoute(); return ()=>h(RouterView,{key:String(route.params.bank)})} }).use(router).mount('#app')
