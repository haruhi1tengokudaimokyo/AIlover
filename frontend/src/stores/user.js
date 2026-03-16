import {defineStore} from 'pinia';
import {ref} from 'vue';
export const useUserStore = defineStore('user', ()=>{
    const id = ref(0)
    const username = ref('')
    const photo = ref('')
    const profile = ref('')
    const accessToken = ref('')

    function isLogin(){
        return !!accessToken.value  //必须带value，不带value永远不为空
    }
    function setAccessToken(token){
        accessToken.value = token
    }
    function setUserInfo(data){
        id.value = data.user_id          //这里有问题
        username.value = data.username
        photo.value = data.photo
        profile.value = data.profile
    }
    function logout(){
        id.value = 0
        username.value = ''
        photo.value = ''
        accessToken.value = ''
        accessToken.value = ''
    }
    return {
        id,
        username,
        photo,
        profile,
        accessToken,
        isLogin,
        setAccessToken,
        setUserInfo,
        logout,
    }
})