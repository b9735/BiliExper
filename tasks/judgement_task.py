from BiliClient import asyncbili
from .push_message_task import webhook
import logging
import random
from asyncio import TimeoutError, sleep
from concurrent.futures import CancelledError
from async_timeout import timeout
from typing import Awaitable, Tuple


async def judgement_task(biliapi: asyncbili, 
                         task_config: dict
                         ) -> Awaitable:
    '''风纪委员会投票任务'''
    try:
        ret = await biliapi.juryInfo()
    except Exception as e:
        logging.warning(f'{biliapi.name}: 获取风纪委员信息异常，原因为{str(e)}，跳过投票')
        webhook.addMsg('msg_simple', f'{biliapi.name}:风纪委投票失败\n')
        return
    if ret["code"] == 25005:
        logging.warning(f'{biliapi.name}: 风纪委员投票失败，请去https://www.bilibili.com/judgement/apply 申请成为风纪委员')
        webhook.addMsg('msg_simple', f'{biliapi.name}:不是风纪委\n')
        return
    elif ret["code"] != 0:
        logging.warning(f'{biliapi.name}: 风纪委员投票失败，信息为：{ret["msg"]}')
        webhook.addMsg('msg_simple', f'{biliapi.name}:风纪委投票失败\n')
        return
    if ret["data"]["status"] != 1:
        logging.warning(f'{biliapi.name}: 风纪委员投票失败，风纪委员资格失效')
        webhook.addMsg('msg_simple', f'{biliapi.name}:风纪委资格失效\n')
        return

    logging.info(f'{biliapi.name}: 拥有风纪委员身份，开始获取案件投票，当前裁决正确率为：{ret["data"]["rightRadio"]}%')
    webhook.addMsg('msg_simple', f'{biliapi.name}:风纪委当前裁决正确率为：{ret["data"]["rightRadio"]}%\n')

    params = task_config.get("params", {})
    isRandom = task_config.get("isRandom", False)
    vote_index = task_config.get("vote_index", 2)
    vote_num = task_config.get("vote_num", 20)
    check_interval = task_config.get("check_interval", 420)
    Timeout = task_config.get("timeout", 850)
    run_once = task_config.get("run_once", False)

    over = False
    su = 0
    try:
        async with timeout(Timeout):
            while True:
                while True:
                    try:
                        ret = await biliapi.juryCaseObtain()
                    except CancelledError as e:
                        raise e
                    except Exception as e:
                        logging.warning(f'{biliapi.name}: 获取风纪委员案件异常，原因为{str(e)}，跳过本次投票')
                        break
                    if ret["code"] == 25008:
                        logging.info(f'{biliapi.name}: 风纪委员没有新案件了')
                        break
                    elif ret["code"] == 25014:
                        over = True
                        logging.info(f'{biliapi.name}: 风纪委员案件已审满')
                        webhook.addMsg('msg_simple', f'{biliapi.name}:风纪委员案件已审满\n')
                        break
                    elif ret["code"] != 0:
                        logging.warning(f'{biliapi.name}: 获取风纪委员案件失败，信息为：{ret["message"]}')
                        break
                    case_id = ret["data"]["case_id"]
                    params = task_config.get("params", {})
                    vote_text = ""
                    vote_cd = 15
                    
                    try:
                        ret = await biliapi.juryCaseInfo(case_id)
                    except CancelledError as e:
                        raise e
                    except Exception as e:
                        logging.warning(f'{biliapi.name}: 获取风纪委员案件信息失败，原因为{str(e)}，使用默认投票参数')
                    else:
                        if ret["code"] == 0 :
                            vote_items = ret["data"]["vote_items"]
                            vote_cd = ret["data"]["vote_cd"]
                            params = params.copy()
                            if isRandom:
                                vote_item = random.choice(vote_items)
                            else:
                                vote_item = vote_items[vote_index]
                            params["vote"] = vote_item["vote"]
                            vote_text = vote_item["vote_text"]
                            logging.info(f'{biliapi.name}: 风纪委员成功为id为{case_id}的案件成功生成默认投票参数：{vote_text}')
                        else:
                            logging.warning(f'{biliapi.name}: 获取风纪委员案件信息失败，原因为{str(e)}，无法生成默认投票参数')
                    
                    try:
                        ret = await biliapi.juryCaseOpinion(case_id)
                    except CancelledError as e:
                        raise e
                    except Exception as e:
                        logging.warning(f'{biliapi.name}: 获取风纪委员案件他人投票结果异常，原因为{str(e)}，使用默认投票参数')
                    else:
                        if ret["code"] == 0 :
                            opinions = ret["data"]["list"]
                            if len(opinions):
                                opinion = random.choice(opinions)
                                vote = opinion["vote"]
                                vote_text  = opinion["vote_text"]
                                params = params.copy()
                                params["vote"] = vote
                                logging.info(f'{biliapi.name}: 风纪委员成功为id为{case_id}的案件获取他人投票参数：{vote_text}')
                        else:
                            logging.warning(f'{biliapi.name}: 获取风纪委员案件他人投票结果异常，原因为{ret["message"]}，使用默认投票参数')
                    
                    initParams=params.copy()
                    initParams["vote"]='0'
                    await biliapi.juryVote(case_id, **initParams)
                    
                    try:
                        await sleep(vote_cd)
                        ret = await biliapi.juryVote(case_id, **params) #将参数params展开后传参
                    except CancelledError as e:
                        raise e
                    except Exception as e:
                        logging.warning(f'{biliapi.name}: 风纪委员投票id为{case_id}的案件异常，原因为{str(e)}')
                    else:
                        if ret["code"] == 0:
                            su += 1
                            logging.info(f'{biliapi.name}: 风纪委员成功为id为{case_id}的案件投({vote_text})票')
                        else:   
                            logging.warning(f'{biliapi.name}: 风纪委员投票id为{case_id}的案件失败，信息为：{ret["message"]}')

                if over or run_once or su >= vote_num:
                    logging.info(f'{biliapi.name}: 风纪委员投票成功完成{su}次后退出')
                    break
                else:
                    logging.info(f'{biliapi.name}: 风纪委员投票等待{check_interval}s后继续获取案件')
                    await sleep(check_interval)

    except TimeoutError:
        logging.info(f'{biliapi.name}: 风纪委员投票任务超时({Timeout}秒)退出')
    except CancelledError:
        logging.warning(f'{biliapi.name}: 风纪委员投票任务被强制取消')

    webhook.addMsg('msg_simple', f'{biliapi.name}:风纪委投票成功{su}次\n')
