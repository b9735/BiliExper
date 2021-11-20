from BiliClient import asyncbili
from .push_message_task import webhook
import logging
import random
import time
import itertools
from asyncio import TimeoutError, sleep
from concurrent.futures import CancelledError
from async_timeout import timeout
from typing import Awaitable, Tuple, List


async def judgement_task(biliapi: asyncbili, task_config: dict) -> Awaitable:
    """风纪委员会投票任务"""
    try:
        info = await biliapi.juryInfo()
    except Exception as e:
        logging.warning(f"{biliapi.name}: 获取风纪委员信息异常，原因为{str(e)}，跳过投票")
        webhook.addMsg("msg_simple", f"{biliapi.name}:风纪委投票失败\n")
        return
    if info["code"] == 25005:
        logging.warning(
            f"{biliapi.name}: 风纪委员投票失败，请去https://www.bilibili.com/judgement/apply 申请成为风纪委员"
        )
        webhook.addMsg("msg_simple", f"{biliapi.name}:不是风纪委\n")
        return
    elif info["code"] != 0:
        logging.warning(f'{biliapi.name}: 风纪委员投票失败，信息为：{info["msg"]}')
        webhook.addMsg("msg_simple", f"{biliapi.name}:风纪委投票失败\n")
        return
    if info["data"]["status"] != 1:
        logging.warning(f"{biliapi.name}: 风纪委员投票失败，风纪委员资格失效")
        webhook.addMsg("msg_simple", f"{biliapi.name}:风纪委资格失效\n")
        # todo 自动申请成为风纪委员
        if info["data"]["apply_status"] == -1:
            ret = await biliapi.juryApply()
        return
    remain_days = round( (info["data"]["term_end"]-time.time())/(60*60*24) )
    logging.info(
        f'{biliapi.name}: 拥有风纪委员身份，任期剩余{remain_days}天'
    )
    webhook.addMsg(
        "msg_simple", f'{biliapi.name}:拥有风纪委员身份，任期剩余{remain_days}天\n'
    )

    # 获取统计信息
    try:
        kpi = await biliapi.juryKpi()
    except Exception as e:
        logging.warning(f"{biliapi.name}: 获取风纪委员统计信息异常，原因为{str(e)}")
        webhook.addMsg("msg_simple", f"{biliapi.name}:获取风纪委员统计信息异常\n")
    else:
        if kpi["code"] != 0:
            logging.warning(f'{biliapi.name}: 获取风纪委员统计信息失败，信息为：{kpi["msg"]}')
        else:
            logging.info(
                f'{biliapi.name}: 当前风纪委案件裁决正确率为：{kpi["data"]["accuracy_rate"]}%'
            )
            webhook.addMsg(
                "msg_simple",
                f'{biliapi.name}: 当前风纪委案件裁决正确率为：{kpi["data"]["accuracy_rate"]}%\n',
            )

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
                        logging.warning(
                            f"{biliapi.name}: 获取风纪委员案件异常，原因为{str(e)}，跳过本次投票"
                        )
                        break
                    if ret["code"] == 25008:
                        logging.info(f"{biliapi.name}: 风纪委员没有新案件了")
                        break
                    elif ret["code"] == 25014:
                        over = True
                        logging.info(f"{biliapi.name}: 风纪委员案件已审满")
                        webhook.addMsg("msg_simple", f"{biliapi.name}:风纪委员案件已审满\n")
                        break
                    elif ret["code"] != 0:
                        logging.warning(
                            f'{biliapi.name}: 获取风纪委员案件失败，信息为：{ret["message"]}'
                        )
                        break
                    case_id = ret["data"]["case_id"]
                    params = task_config.get("params", {})
                    vote_text = ""
                    vote_cd = 15

                    try:
                        await sleep(1)
                        ret = await biliapi.juryCaseInfo(case_id)
                        start_time = int(time.time())
                    except CancelledError as e:
                        raise e
                    except Exception as e:
                        logging.warning(
                            f"{biliapi.name}: 获取风纪委员案件信息失败，原因为{str(e)}，使用默认投票参数"
                        )
                    else:
                        if ret["code"] == 0:
                            vote_items: List[Dict[str, int or str]] = ret["data"][
                                "vote_items"
                            ]
                            vote_dict = {}
                            for item in vote_items:
                                vote_dict[item["vote"]] = item
                                vote_dict[item["vote"]]["count"] = 0
                            vote_cd = ret["data"]["vote_cd"]
                            params = params.copy()
                            if isRandom:
                                my_vote = random.choice(vote_items)
                            else:
                                my_vote = vote_items[vote_index]
                            params["vote"] = vote_item["vote"]
                            logging.info(
                                f"{biliapi.name}: 风纪委员成功为id为{case_id}的案件成功生成默认投票参数：{my_vote['vote_text']}"
                            )
                        else:
                            logging.warning(
                                f"{biliapi.name}: 获取风纪委员案件信息失败，原因为{str(e)}，无法生成默认投票参数"
                            )

                    # 获取众议观点
                    try:
                        opinions = []
                        pn_iters = itertools.count(1)
                        for pn in pn_iters:
                            # 最多获取10页
                            if pn > 10:
                                break
                            await sleep(0.5)
                            ret = await biliapi.juryCaseOpinion(case_id, pn=pn, ps=20)
                            if ret["code"] == 0:
                                opinions_current = ret["data"]["list"]
                                if len(opinions_current) != 0:
                                    opinions.append(opinions_current)
                                    if len(opinions_current) < 20:
                                        break
                                else:
                                    break
                            else:
                                logging.warning(
                                    f'{biliapi.name}: 获取风纪委员案件众议观点异常，原因为{ret["message"]}，将使用默认投票参数'
                                )
                                break
                    except CancelledError as e:
                        raise e
                    except Exception as e:
                        logging.warning(
                            f"{biliapi.name}: 获取风纪委员案件众议观点异常，原因为{str(e)}，使用默认投票参数"
                        )
                    finally:
                        if len(opinions):
                            # 统计众议观点，选择最多的观点
                            for opinion in opinions:
                                # {
                                #     "opid": 6858615,
                                #     "mid": 434071705,
                                #     "uname": "",
                                #     "face": "",
                                #     "vote": 12,
                                #     "vote_text": "普通",
                                #     "content": "很普通",
                                #     "anonymous": 0,
                                #     "like": 0,
                                #     "hate": 0,
                                #     "like_status": 0,
                                #     "vote_time": 1637208209,
                                #     "insiders": 0
                                # }
                                vote_dict[opinion["vote"]]["count"] += (
                                    1 + opinion["like"] - opinion["hate"]
                                )
                            vote_items.sort(
                                key=lambda elem: vote_dict[elem["vote"]]["count"],
                                reverse=True,
                            )
                            params = params.copy()
                            params["vote"] = vote_items[0]["vote"]
                            info_text = f"{biliapi.name}: 风纪委员成功为id为{case_id}的案件获取他人投票参数：{vote_items[0]['vote_text']},众议观点:"
                            for item in vote_items:
                                info_text += (
                                    f"({vote_item['vote']} {vote_item['vote_text']}票),"
                                )
                            logging.info(info_text.rstrip(","))
                        else:
                            logging.warning(f"{biliapi.name}: 风纪委员案件未获取到众议观点，将使用默认投票参数")

                    # 初始的空投票
                    initParams = params.copy()
                    initParams["vote"] = "0"
                    biliapi.juryVote(case_id, **initParams)
                    # 真正的投票
                    try:
                        wait_time = vote_cd - (int(time.time()) - start_time)
                        if wait_time > 0:
                            await sleep(wait_time)
                        ret = await biliapi.juryVote(
                            case_id, **params
                        )  # 将参数params展开后传参
                    except CancelledError as e:
                        raise e
                    except Exception as e:
                        logging.warning(
                            f"{biliapi.name}: 风纪委员投票id为{case_id}的案件异常，原因为{str(e)}"
                        )
                    else:
                        if ret["code"] == 0:
                            su += 1
                            logging.info(
                                f"{biliapi.name}: 风纪委员成功为id为{case_id}的案件投({vote_dict[params['vote']]['vote_text']})票"
                            )
                        else:
                            logging.warning(
                                f'{biliapi.name}: 风纪委员投票id为{case_id}的案件失败，信息为：{ret["message"]}'
                            )

                if over or run_once or su >= vote_num:
                    logging.info(f"{biliapi.name}: 风纪委员投票成功完成{su}次后退出")
                    break
                else:
                    logging.info(f"{biliapi.name}: 风纪委员投票等待{check_interval}s后继续获取案件")
                    await sleep(check_interval)

    except TimeoutError:
        logging.info(f"{biliapi.name}: 风纪委员投票任务超时({Timeout}秒)退出")
    except CancelledError:
        logging.warning(f"{biliapi.name}: 风纪委员投票任务被强制取消")

    webhook.addMsg("msg_simple", f"{biliapi.name}:风纪委投票成功{su}次\n")
