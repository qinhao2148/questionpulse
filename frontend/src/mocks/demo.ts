export type PulseStatus = 'open' | 'addressing' | 'awaiting_feedback' | 'closed'

export interface DemoCluster {
  id: string
  title: string
  people: number
  questions: number
  waiting: string
  status: PulseStatus
  confused: number
  understood: number
  samples: string[]
}

export const demoClusters: DemoCluster[] = [
  {
    id: 'recursion-exit', title: '递归在什么条件下结束？', people: 18, questions: 23,
    waiting: '08:42', status: 'addressing', confused: 0, understood: 0,
    samples: ['递归为什么一定要有结束条件？', '没有 base case 程序是不是停不下来？', '终止条件应该写在哪里？'],
  },
  {
    id: 'async-order', title: '异步任务的执行顺序如何判断？', people: 12, questions: 15,
    waiting: '06:18', status: 'open', confused: 0, understood: 0,
    samples: ['Promise 回调为什么比 setTimeout 先执行？', '连续两个 await 的顺序怎么看？'],
  },
  {
    id: 'db-index', title: '哪些查询无法使用索引？', people: 9, questions: 11,
    waiting: '04:51', status: 'awaiting_feedback', confused: 3, understood: 6,
    samples: ['前导模糊查询为什么不走索引？', '函数包住字段以后索引还有效吗？'],
  },
  {
    id: 'http-status', title: '404 和 500 分别由谁处理？', people: 6, questions: 7,
    waiting: '02:33', status: 'closed', confused: 1, understood: 5,
    samples: ['404 是前端路由还是后端返回？', '服务器报 500 时应该先查哪里？'],
  },
]

export const statusLabel: Record<PulseStatus, string> = {
  open: '待处理', addressing: '讲解中', awaiting_feedback: '等待反馈', closed: '已关闭',
}
