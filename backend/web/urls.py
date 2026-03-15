
from django.urls import path
from web.views.index import index
from web.views.user.accout.login import LoginView
from web.views.user.accout.logout import LogoutView
from web.views.user.accout.register import RegisterView
from web.views.user.accout.refresh_token import RefreshTokenView
urlpatterns = [
    path('api/user/account/login/',LoginView.as_view()),
    path('api/user/account/logout/',LogoutView.as_view()),
    path('api/user/account/register/',RegisterView.as_view()),
    path('api/user/account/refresh_token/',RefreshTokenView.as_view()),
    path('',index),
]
