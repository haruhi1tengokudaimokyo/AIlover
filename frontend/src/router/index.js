import { createRouter, createWebHistory } from 'vue-router'
const HomePageIndex = () => import('@/views/homepage/HomePageIndex.vue')
const FriendIndex = () => import('@/views/friend/FriendIndex.vue')
const CreateIndex = () => import('@/views/create/CreateIndex.vue')
const NotFoundIndex = () => import('@/views/error/NotFoundIndex.vue')
const LoginIndex = () => import('@/views/user/account/LoginIndex.vue')
const RegisterIndex = () => import('@/views/user/account/RegisterIndex.vue')
const SpaceIndex = () => import('@/views/user/space/SpaceIndex.vue')
const ProfileIndex = () => import('@/views/user/profile/ProfileIndex.vue')
import {useUserStore} from "@/stores/user.js";
const UpdateCharacter = () => import('@/views/create/character/UpdateCharacter.vue')
const SettingsIndex = () => import('@/views/settings/SettingsIndex.vue')


const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    { path: '/chat/:friendId', name: 'chat-workspace', component: () => import('@/views/friend/ChatWorkspace.vue'), meta: { needLogin: true } },
    { path: '/settings/', component: SettingsIndex, name: 'settings-index', meta: { needLogin: true } },

    {
      path: '/',
      component: HomePageIndex,
      name: 'homepage-index',
      meta: {
        needLogin: false,
      },
    },
    {
      path: '/friend/',
      component: FriendIndex,
      name: 'friend-index',
      meta: {
        needLogin: true,
      },
    },
    {
      path: '/create/',
      component: CreateIndex,
      name: 'create-index',
      meta: {
        needLogin: true,
      },
    },
    {
    path:'/create/character/update/:character_id/',
    component:UpdateCharacter,
    name:'update-character',
    meta:{
      needLogin: true,
    }
},
    {
      path: '/404/',
      component: NotFoundIndex,
      name: '404',
      meta: {
        needLogin: false,
      },
    },
    {
      path: '/user/account/login',
      component: LoginIndex,
      name: 'user-account-login-index',
      meta: {
        needLogin: false,
      },
    },
    {
      path: '/user/account/register',
      component: RegisterIndex,
      name: 'user-account-register-index',
      meta: {
        needLogin: false,
      },
    },
    {
      path: '/user/space/:user_id/',
      component: SpaceIndex,
      name: 'user-space-index',
      meta: {
        needLogin: false,
      },
    },
    {
      path: '/user/profile/',
      component: ProfileIndex,
      name: 'user-profile-index',
      meta: {
        needLogin: false,
      },
    },
    {
       path: '/:pathMatch(.*)*',
       component: NotFoundIndex,
       name: 'not-found',
       meta: {
          needLogin: false,
       },
    }
  ],
})


router.beforeEach((to)=>{
  const user = useUserStore()
  if(to.meta.needLogin && user.hasPulledUserInfo && !user.isLogin()){
    return {
      name:'user-account-login-index',
      query: { redirect: to.fullPath },
    }
  }
  return true
})
export default router
