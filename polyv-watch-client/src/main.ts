// 入口配置需要在最前面导入
import './entry-config';

import { mainFactory } from './entry-helper';
import Vue from 'vue';
import WatchApp from './app/watch-app.vue';
import { prepareWatchTab } from './questionpulse/tab-guard';

console.info(
  '%c WatchApp build info: %s, %s, %s, %s',
  'color: white;background-color: #0070ed;padding: 5px 5px',
  PROJECT_VERSION,
  PROJECT_BUILD_TIME,
  `sdkLoaderEnv: ${WATCH_SDK_ENV}`,
  `sdkInjectMode: ${IN_SDK_INJECT_MODE}`,
);

// 保利威一个观众只允许一个活跃会话，重复的标签页会互相踢下线并跳到错误页。
// 所以挂载播放器之前先给标签页定好身份，并确认这个学生没有被别的标签页占着。
prepareWatchTab()
  .catch(() => false)
  .then(redirected => {
    if (!redirected) mainFactory(WatchApp as unknown as Vue);
  });
