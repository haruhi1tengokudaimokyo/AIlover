<script setup>

import Photo from "@/views/create/character/components/Photo.vue";
import Name from "@/views/create/character/components/Name.vue";
import Profile from "@/views/create/character/components/Profile.vue";
import BackgroundImage from "@/views/create/character/components/BackgroundImage.vue";
import {onMounted, ref, useTemplateRef} from "vue";
import {base64ToFile} from "@/js/utils/base64_to_file.js";
import api from "@/js/http/api.js";
import {useRoute, useRouter} from "vue-router";
import {useUserStore} from "@/stores/user.js";

const user = useUserStore()
const router = useRouter()
const route = useRoute()
const characterId = route.params.character_id
const character = ref(null)
const voice = ref('')
const greeting = ref('')
const quickReplies = ref('')

onMounted(async () => {
  try{
    const res = await api.get('/api/create/character/get_single/',{//向后端发送一个请求
      params:{
        character_id:characterId,
      }
    })
    const data = res.data
    if(data.result === 'success'){
      character.value = data.character
      voice.value = data.character.voice || ''
      greeting.value = data.character.greeting || ''
      quickReplies.value = JSON.parse(data.character.quick_replies || '[]').join('\n')
    }
  } catch (err){
  }
})

const photoRef = useTemplateRef('photo-ref') //四个引用
const nameRef = useTemplateRef('name-ref')
const profileRef = useTemplateRef('profile-ref')
const backgroundImageRef = useTemplateRef('background-image-ref')
const errorMessage =ref('')

//对接后端的函数
async function handleUpdate(){
  const photo = photoRef.value.myPhoto //获取四个变量
  const name = nameRef.value.myName?.trim()//去掉前后空格,为空返回空，不空调用.trim()
  const profile = profileRef.value.myProfile?.trim()
  const backgroundImage = backgroundImageRef.value.myBackgroundImage

  errorMessage.value = ''
  if(!photo){
    errorMessage.value='头像不得为空'
  }else if(!name){
    errorMessage.value='名字不得为空'
  }else if(!profile){
    errorMessage.value='角色简介不得为空'
  }else if(!backgroundImage){
    errorMessage.value='聊天背景不得为空'
  }else{
    const formData = new FormData()//对接后端，因为传文件创建一个FORM表单数据FormData
    formData.append('character_id',characterId)
    formData.append('name',name)
    formData.append('profile',profile)
    formData.append('voice', voice.value.trim())
    formData.append('greeting', greeting.value.trim())
    formData.append('quick_replies', JSON.stringify(quickReplies.value.split('\n').map(text => text.trim()).filter(Boolean)))

    if (photo !== character.value.photo){
      formData.append('photo',base64ToFile(photo,'photo.png'))
    }

    if (backgroundImage !== character.value.background_image){
    formData.append('background_image',base64ToFile(backgroundImage,'background_image.png')) //key与`/api/create/character/create/`的变量一致
    }

    try{
      const res = await api.post('/api/create/character/update/',formData)//对接后端的请求
      const data = res.data //获取返回结果
      if(data.result === 'success'){//成功自动跳转用户主页
        await router.push({
          name:'user-space-index',
          params:{
            user_id: user.id,
          }
        })
      }else{
        errorMessage.value = data.result
      }

    }catch (err){
      errorMessage.value = err.response?.data?.result || '更新失败，请重试'
    }
  }
}
</script>

<template>
  <div v-if="character" class="flex justify-center"> <!-- 如果有角色才显示 -->
    <div class="card w-120 bg-base-200 shadow-sm mt-18">
      <div class="card-body">
        <h3 class="text-lg font-bold my-4">更新角色</h3>
        <Photo ref="photo-ref" :photo="character.photo"/>
        <Name ref="name-ref" :name="character.name"/>
        <Profile ref="profile-ref" :profile="character.profile"/>
        <label class="text-sm">音色 ID<input v-model="voice" maxlength="100" class="input w-full" placeholder="填写语音服务提供的音色 ID"></label>
        <label class="text-sm">开场白<textarea v-model="greeting" maxlength="2000" rows="3" class="textarea w-full"></textarea></label>
        <label class="text-sm">快捷话题（每行一条，最多10条）<textarea v-model="quickReplies" rows="3" class="textarea w-full"></textarea></label>
        <BackgroundImage ref="background-image-ref" :backgroundImage="character.background_image"/>

        <p v-if="errorMessage" class="text-sm text-red-500">{{errorMessage}}</p>

        <div class="flex justify-center">
          <button @click="handleUpdate" class="btn btn-neutral w-60 mt-2">更新</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>

</style>
