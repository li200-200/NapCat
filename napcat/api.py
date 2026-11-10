#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQBot —— NapCat / OneBot v11 接口封装。

NapCat 4.18.42 暴露的每一个 OneBot 接口，在本类里都有一个同名方法。
方法形态对齐易语言原型：

    .子程序 发送好友消息, 文本型, 公开, 成功返回的time用于撤回消息
    .参数 好友QQ, 长整数型
    .参数 发送内容, 文本型
    .参数 Random, 长整数型, 参考 可空, 撤回消息用
    .参数 Req, 整数型, 参考 可空, 撤回消息用

类型对应关系：

    文本型      -> str
    长整数型    -> int            （Python 的 int 是任意精度，天然覆盖 int64）
    整数型      -> int
    参考        -> Ref            （可变容器，方法内部写 .value）
    可空        -> 默认值 None
    公开        -> 无下划线前缀的方法名

撤回三元组
----------
NapCat 的 ``send_*_msg`` 只返回 ``message_id``，而易语言接口按
``(time, random, req)`` 三元组撤回。三者在 ``get_msg`` 应答里的对应关系：

    time    = time           （unix 秒）
    random  = message_seq
    req     = real_id

所以本类在发送成功后立刻调一次 ``get_msg`` 补齐这三个值，并维护
``(time, random, req) -> message_id`` 对照表，让 ``recall_friend_msg``
能反查出 ``delete_msg`` 真正需要的 id。

本文件由 NapCat 源码自动生成，请勿手工修改生成出来的方法体。
"""

from __future__ import annotations

from typing import Any

import requests


class Ref:
    """模拟易语言「参数 ..., 参考」的传址语义。

    被调用方写入 :attr:`value`，调用方随后读取::

        random = Ref()
        req = Ref()
        t = bot.send_friend_msg(qq, "hi", random, req)
        print(t, random.value, req.value)
    """

    __slots__ = ("value",)

    def __init__(self, value: Any = None) -> None:
        self.value = value

    def __int__(self) -> int:
        return int(self.value or 0)

    def __bool__(self) -> bool:
        return self.value is not None

    def __repr__(self) -> str:
        return f"Ref({self.value!r})"


class QQBotError(RuntimeError):
    """NapCat 返回非 0 retcode 时抛出。"""

    def __init__(self, action: str, retcode: int, message: str) -> None:
        super().__init__(f"{action} 调用失败 (retcode={retcode})：{message}")
        self.action = action
        self.retcode = retcode
        self.message = message


class QQBot:
    """NapCat OneBot HTTP 接口的完整封装。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3000",
        access_token: str = "",
        timeout: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"
        if access_token:
            self._session.headers["Authorization"] = f"Bearer {access_token}"

        # (time, random, req) -> message_id，供三元组撤回使用
        self._recall_index: dict[tuple[int, int, int], int] = {}
        # time -> message_id，让只传 time 的撤回也能工作
        self._recall_by_time: dict[int, int] = {}

    # ------------------------------------------------------------------ #
    # 底层传输
    # ------------------------------------------------------------------ #
    def call(self, action: str, **params: Any) -> Any:
        """向 OneBot HTTP 端点 POST 一个接口，返回应答里的 ``data``。

        ``retcode`` 非 0 时抛 :class:`QQBotError`。
        """
        url = f"{self.base_url}/{action}"
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            response = self._session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise QQBotError(action, -1, f"网络错误：{exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise QQBotError(action, response.status_code,
                             response.text[:300]) from exc

        retcode = body.get("retcode")
        if retcode not in (0, None):
            raise QQBotError(action, int(retcode or 0),
                             body.get("message") or body.get("wording") or "")
        return body.get("data")

    def call_raw(self, action: str, **params: Any) -> dict:
        """与 :meth:`call` 相同，但返回完整应答（status / retcode / data）。"""
        url = f"{self.base_url}/{action}"
        payload = {k: v for k, v in params.items() if v is not None}
        response = self._session.post(url, json=payload, timeout=self.timeout)
        try:
            return response.json()
        except ValueError:
            return {"status": "failed", "retcode": response.status_code,
                    "message": response.text[:300], "data": None}

    # ------------------------------------------------------------------ #
    # 撤回辅助
    # ------------------------------------------------------------------ #
    def _register_recall(self, message_id: Any) -> tuple[int, int, int]:
        """查一次 ``get_msg``，登记 (time, random, req) 三元组。"""
        mid = int(message_id)
        try:
            info = self.call("get_msg", message_id=mid) or {}
        except QQBotError:
            info = {}
        t = int(info.get("time") or 0)
        seq = int(info.get("message_seq") or mid)
        real = int(info.get("real_id") or mid)
        self._recall_index[(t, seq, real)] = mid
        if t:
            self._recall_by_time[t] = mid
        return t, seq, real

    def resolve_message_id(
        self,
        time: int = 0,
        random: int = 0,
        req: int = 0,
        message_id: int = 0,
    ) -> int:
        """解析出 ``delete_msg`` 真正需要的 ``message_id``。

        空字符串（``send_friend_msg`` 失败时的返回值）会被当成 0，
        这样调用方可以直接把发送结果原样传进来，不用先判断。
        """
        time = int(time or 0)
        random = int(random or 0)
        req = int(req or 0)

        if message_id:
            return int(message_id)
        hit = self._recall_index.get((time, random, req))
        if hit:
            return hit
        # 只给 time 的情况：同一秒内的 unix 时间戳实际上唯一
        hit = self._recall_by_time.get(time)
        if hit:
            return hit
        return int(random or req or 0)

    def recall(
        self,
        time: int = 0,
        random: int = 0,
        req: int = 0,
        message_id: int = 0,
    ) -> bool:
        """按三元组或 message_id 撤回消息，成功返回 True。"""
        mid = self.resolve_message_id(time, random, req, message_id)
        if not mid:
            return False
        try:
            self.call("delete_msg", message_id=mid)
        except QQBotError:
            return False
        self._recall_index.pop((int(time or 0), int(random or 0), int(req or 0)), None)
        self._recall_by_time.pop(int(time or 0), None)
        return True


    def handle_quick_operation(
        self,
        context: Any,
        operation: Any,
    ) -> Any:
        """处理快速操作。
        
        OneBot 接口：``.handle_quick_operation``
        
        必填参数：
            context (Any) —— 事件上下文
            operation (Any) —— 要执行的操作
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            '.handle_quick_operation',
            context=context,
            operation=operation,
        )

    def ArkShareGroup(
        self,
        group_id: str,
    ) -> Any:
        """获取群 Ark 分享卡片。
        
        OneBot 接口：``ArkShareGroup``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'ArkShareGroup',
            group_id=group_id,
        )

    def ArkSharePeer(
        self,
        user_id: str = None,
        group_id: str = None,
        phone_number: str = '',
    ) -> Any:
        """获取用户 Ark 分享卡片。
        
        OneBot 接口：``ArkSharePeer``
        
        可选参数：
            user_id (str, 默认 None) —— QQ号
            group_id (str, 默认 None) —— 群号
            phone_number (str, 默认 '') —— 手机号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'ArkSharePeer',
            user_id=user_id,
            group_id=group_id,
            phone_number=phone_number,
        )

    def ForwardQzonePublicFeed(
        self,
        feed: Any,
        reason: str = '',
    ) -> Any:
        """转发空友爱看动态。
        
        OneBot 接口：``ForwardQzonePublicFeed``
        
        必填参数：
            feed (Any) —— 说说对象
        
        可选参数：
            reason (str, 默认 '') —— 转发附言，默认空字符串；数字或布尔值会转为文本
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'ForwardQzonePublicFeed',
            feed=feed,
            reason=reason,
        )

    def _del_group_notice(
        self,
        group_id: str,
        notice_id: str,
    ) -> Any:
        """删除群公告。
        
        OneBot 接口：``_del_group_notice``
        
        必填参数：
            group_id (str) —— 群号
            notice_id (str) —— 公告ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            '_del_group_notice',
            group_id=group_id,
            notice_id=notice_id,
        )

    def _get_group_notice(
        self,
        group_id: str,
    ) -> Any:
        """获取群公告。
        
        OneBot 接口：``_get_group_notice``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            '_get_group_notice',
            group_id=group_id,
        )

    def _get_model_show(
        self,
        model: str = None,
    ) -> Any:
        """获取机型显示。
        
        OneBot 接口：``_get_model_show``
        
        可选参数：
            model (str, 默认 None) —— 模型名称
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            '_get_model_show',
            model=model,
        )

    def _mark_all_as_read(
        self,
    ) -> Any:
        """标记所有消息已读。
        
        OneBot 接口：``_mark_all_as_read``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            '_mark_all_as_read',
        )

    def _send_group_notice(
        self,
        group_id: str,
        content: str,
        image: str = None,
        pinned: int = 0,
        type: int = 1,
        confirm_required: int = 1,
        is_show_edit_card: int = 0,
        tip_window_type: int = 0,
    ) -> Any:
        """发送群公告。
        
        OneBot 接口：``_send_group_notice``
        
        必填参数：
            group_id (str) —— 群号
            content (str) —— 公告内容
        
        可选参数：
            image (str, 默认 None) —— 公告图片路径或 URL
            pinned (int, 默认 0) —— 是否置顶 (0/1)
            type (int, 默认 1) —— 类型 (默认为 1)
            confirm_required (int, 默认 1) —— 是否需要确认 (0/1)
            is_show_edit_card (int, 默认 0) —— 是否显示修改群名片引导 (0/1)
            tip_window_type (int, 默认 0) —— 弹窗类型 (默认为 0)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            '_send_group_notice',
            group_id=group_id,
            content=content,
            image=image,
            pinned=pinned,
            type=type,
            confirm_required=confirm_required,
            is_show_edit_card=is_show_edit_card,
            tip_window_type=tip_window_type,
        )

    def _set_model_show(
        self,
    ) -> Any:
        """设置机型。
        
        OneBot 接口：``_set_model_show``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            '_set_model_show',
        )

    def add_custom_face(
        self,
        file: str,
        emoji_id: str = None,
        package_id: str = None,
        file_name: str = None,
        file_size: str = None,
        md5: str = None,
        is_mark_face: bool = None,
        is_origin: bool = None,
    ) -> Any:
        """添加自定义表情。
        
        OneBot 接口：``add_custom_face``
        
        必填参数：
            file (str) —— 本地表情文件路径
        
        可选参数：
            emoji_id (str, 默认 None) —— 表情ID，未提供时传空字符串
            package_id (str, 默认 None) —— 表情包ID，未提供时传0
            file_name (str, 默认 None) —— 文件名，未提供时从file路径取basename
            file_size (str, 默认 None) —— 文件大小，未提供时读取本地文件
            md5 (str, 默认 None) —— 文件MD5，未提供时读取本地文件计算
            is_mark_face (bool, 默认 None) —— 是否商城表情
            is_origin (bool, 默认 None) —— 是否原图
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'add_custom_face',
            file=file,
            emoji_id=emoji_id,
            package_id=package_id,
            file_name=file_name,
            file_size=file_size,
            md5=md5,
            is_mark_face=is_mark_face,
            is_origin=is_origin,
        )

    def bot_exit(
        self,
    ) -> Any:
        """退出登录。
        
        OneBot 接口：``bot_exit``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'bot_exit',
        )

    def can_send_image(
        self,
    ) -> Any:
        """是否可以发送图片。
        
        OneBot 接口：``can_send_image``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'can_send_image',
        )

    def can_send_record(
        self,
    ) -> Any:
        """是否可以发送语音。
        
        OneBot 接口：``can_send_record``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'can_send_record',
        )

    def cancel_group_album_media_like(
        self,
        group_id: str,
        album_id: str,
        batch_id: str,
        lloc: str = None,
    ) -> Any:
        """取消点赞群相册媒体。
        
        OneBot 接口：``cancel_group_album_media_like``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册ID
            batch_id (str) —— 批次 ID
        
        可选参数：
            lloc (str, 默认 None) —— lloc，若对整个上传操作则不填
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'cancel_group_album_media_like',
            group_id=group_id,
            album_id=album_id,
            batch_id=batch_id,
            lloc=lloc,
        )

    def cancel_group_todo(
        self,
        group_id: str,
        message_id: str = None,
        message_seq: str = None,
    ) -> Any:
        """取消群待办。
        
        OneBot 接口：``cancel_group_todo``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            message_id (str, 默认 None) —— 消息ID
            message_seq (str, 默认 None) —— 消息Seq (可选)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'cancel_group_todo',
            group_id=group_id,
            message_id=message_id,
            message_seq=message_seq,
        )

    def cancel_online_file(
        self,
        user_id: str,
        msg_id: str,
    ) -> Any:
        """取消在线文件。
        
        OneBot 接口：``cancel_online_file``
        
        必填参数：
            user_id (str) —— 用户 QQ
            msg_id (str) —— 消息 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'cancel_online_file',
            user_id=user_id,
            msg_id=msg_id,
        )

    def check_url_safely(
        self,
        url: str,
    ) -> Any:
        """检查URL安全性。
        
        OneBot 接口：``check_url_safely``
        
        必填参数：
            url (str) —— 要检查的 URL
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'check_url_safely',
            url=url,
        )

    def clean_cache(
        self,
    ) -> Any:
        """清理缓存。
        
        OneBot 接口：``clean_cache``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'clean_cache',
        )

    def clean_stream_temp_file(
        self,
    ) -> Any:
        """清理流式传输临时文件。
        
        OneBot 接口：``clean_stream_temp_file``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'clean_stream_temp_file',
        )

    def click_inline_keyboard_button(
        self,
        group_id: str,
        bot_appid: str,
        button_id: str = '',
        callback_data: str = '',
        msg_seq: str = '10086',
    ) -> Any:
        """点击内联键盘按钮。
        
        OneBot 接口：``click_inline_keyboard_button``
        
        必填参数：
            group_id (str) —— 群号
            bot_appid (str) —— 机器人AppID
        
        可选参数：
            button_id (str, 默认 '') —— 按钮ID
            callback_data (str, 默认 '') —— 回调数据
            msg_seq (str, 默认 '10086') —— 消息序列号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'click_inline_keyboard_button',
            group_id=group_id,
            bot_appid=bot_appid,
            button_id=button_id,
            callback_data=callback_data,
            msg_seq=msg_seq,
        )

    def comment_qzone(
        self,
        content: Any,
        images: Any,
        feed_ref: Any = None,
        tid: Any = None,
        target_uin: Any = None,
        comment: Any = None,
        reply_user: Any = None,
        comment_id: Any = None,
        comment_uin: Any = None,
        reply_uin: Any = None,
        reply_name: Any = None,
    ) -> Any:
        """评论QQ空间说说。
        
        OneBot 接口：``comment_qzone``
        
        必填参数：
            content (Any) —— 内容
            images (Any) —— 图片列表
        
        可选参数：
            feed_ref (Any, 默认 None) —— 说说引用
            tid (Any, 默认 None) —— 说说/消息 ID
            target_uin (Any, 默认 None) —— 目标 QQ
            comment (Any, 默认 None) —— 附言
            reply_user (Any, 默认 None) —— 被回复用户
            comment_id (Any, 默认 None) —— 评论 ID
            comment_uin (Any, 默认 None) —— 评论者 QQ
            reply_uin (Any, 默认 None) —— 被回复者 QQ
            reply_name (Any, 默认 None) —— 被回复者昵称
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'comment_qzone',
            feed_ref=feed_ref,
            tid=tid,
            target_uin=target_uin,
            content=content,
            comment=comment,
            reply_user=reply_user,
            comment_id=comment_id,
            comment_uin=comment_uin,
            reply_uin=reply_uin,
            reply_name=reply_name,
            images=images,
        )

    def comment_qzone_public_feed(
        self,
        feed: Any,
        content: Any,
    ) -> Any:
        """评论空友爱看动态。
        
        OneBot 接口：``comment_qzone_public_feed``
        
        必填参数：
            feed (Any) —— 说说对象
            content (Any) —— 内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'comment_qzone_public_feed',
            feed=feed,
            content=content,
        )

    def complete_group_todo(
        self,
        group_id: str,
        message_id: str = None,
        message_seq: str = None,
    ) -> Any:
        """完成群待办。
        
        OneBot 接口：``complete_group_todo``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            message_id (str, 默认 None) —— 消息ID
            message_seq (str, 默认 None) —— 消息Seq (可选)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'complete_group_todo',
            group_id=group_id,
            message_id=message_id,
            message_seq=message_seq,
        )

    def create_collection(
        self,
        rawData: str,
        brief: str,
    ) -> Any:
        """创建收藏。
        
        OneBot 接口：``create_collection``
        
        必填参数：
            rawData (str) —— 原始数据
            brief (str) —— 简要描述
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'create_collection',
            rawData=rawData,
            brief=brief,
        )

    def create_flash_task(
        self,
        files: list,
        name: str = None,
        thumb_path: str = None,
        validitySeconds: int = None,
    ) -> Any:
        """创建闪传任务。
        
        OneBot 接口：``create_flash_task``
        
        必填参数：
            files (list) —— 文件列表或单个文件路径
        
        可选参数：
            name (str, 默认 None) —— 任务名称
            thumb_path (str, 默认 None) —— 缩略图路径
            validitySeconds (int, 默认 None) —— 文件集有效期（秒），可选 14 天 1209600 / 90 天 7776000 / 180 天 15552000，默认 1209600
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'create_flash_task',
            files=files,
            name=name,
            thumb_path=thumb_path,
            validitySeconds=validitySeconds,
        )

    def create_group_file_folder(
        self,
        group_id: str,
    ) -> Any:
        """创建群文件目录。
        
        OneBot 接口：``create_group_file_folder``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'create_group_file_folder',
            group_id=group_id,
        )

    def del_group_album_media(
        self,
        group_id: str,
        album_id: str,
        lloc: str,
    ) -> Any:
        """删除群相册媒体。
        
        OneBot 接口：``del_group_album_media``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册ID
            lloc (str) —— 媒体ID (lloc)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'del_group_album_media',
            group_id=group_id,
            album_id=album_id,
            lloc=lloc,
        )

    def delete_custom_face(
        self,
        res_id: list = None,
        id: list = None,
        ids: list = None,
        md5: list = None,
    ) -> Any:
        """删除自定义表情。
        
        OneBot 接口：``delete_custom_face``
        
        可选参数：
            res_id (list, 默认 None) —— fetch_custom_face_detail返回的resId
            id (list, 默认 None) —— native deleteFavEmoji字符串ID，通常为resId
            ids (list, 默认 None) —— native deleteFavEmoji字符串ID列表，通常为resId列表
            md5 (list, 默认 None) —— 表情MD5，不能直接删除，请先通过fetch_custom_face_detail获取resId
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_custom_face',
            res_id=res_id,
            id=id,
            ids=ids,
            md5=md5,
        )

    def delete_essence_msg(
        self,
        message_id: int = None,
        msg_seq: str = None,
        msg_random: str = None,
        group_id: str = None,
    ) -> Any:
        """移出精华消息。
        
        OneBot 接口：``delete_essence_msg``
        
        可选参数：
            message_id (int, 默认 None) —— 消息ID
            msg_seq (str, 默认 None) —— 消息序号
            msg_random (str, 默认 None) —— 消息随机数
            group_id (str, 默认 None) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_essence_msg',
            message_id=message_id,
            msg_seq=msg_seq,
            msg_random=msg_random,
            group_id=group_id,
        )

    def delete_friend(
        self,
        friend_id: str = None,
        user_id: str = None,
        temp_block: bool = None,
        temp_both_del: bool = None,
    ) -> Any:
        """删除好友。
        
        OneBot 接口：``delete_friend``
        
        可选参数：
            friend_id (str, 默认 None) —— 好友 QQ 号
            user_id (str, 默认 None) —— 用户 QQ 号
            temp_block (bool, 默认 None) —— 是否加入黑名单
            temp_both_del (bool, 默认 None) —— 是否双向删除
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_friend',
            friend_id=friend_id,
            user_id=user_id,
            temp_block=temp_block,
            temp_both_del=temp_both_del,
        )

    def delete_group_file(
        self,
        group_id: str,
        file_id: str,
        bus_id: int = None,
        busid: int = None,
    ) -> Any:
        """删除群文件。
        
        OneBot 接口：``delete_group_file``
        
        必填参数：
            group_id (str) —— 群号
            file_id (str) —— 文件ID
        
        可选参数：
            bus_id (int, 默认 None) —— 文件业务ID，默认使用文件列表中的 busid
            busid (int, 默认 None) —— 文件业务ID，兼容 busid 字段
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_group_file',
            group_id=group_id,
            file_id=file_id,
            bus_id=bus_id,
            busid=busid,
        )

    def delete_group_folder(
        self,
        group_id: str,
        folder_id: str = None,
        folder: str = None,
    ) -> Any:
        """删除群文件目录。
        
        OneBot 接口：``delete_group_folder``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            folder_id (str, 默认 None) —— 文件夹ID
            folder (str, 默认 None) —— 文件夹ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_group_folder',
            group_id=group_id,
            folder_id=folder_id,
            folder=folder,
        )

    def delete_msg(
        self,
        message_id: int,
    ) -> Any:
        """撤回消息。
        
        OneBot 接口：``delete_msg``
        
        必填参数：
            message_id (int) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_msg',
            message_id=message_id,
        )

    def delete_qzone_msg(
        self,
        tid: Any,
    ) -> Any:
        """删除QQ空间说说。
        
        OneBot 接口：``delete_qzone_msg``
        
        必填参数：
            tid (Any) —— 说说/消息 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_qzone_msg',
            tid=tid,
        )

    def delete_qzone_public_comment(
        self,
        feed: Any,
        comment: Any,
    ) -> Any:
        """删除空友爱看评论。
        
        OneBot 接口：``delete_qzone_public_comment``
        
        必填参数：
            feed (Any) —— 说说对象
            comment (Any) —— 附言
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_qzone_public_comment',
            feed=feed,
            comment=comment,
        )

    def delete_qzone_public_reply(
        self,
        feed: Any,
        comment: Any,
        reply: Any,
    ) -> Any:
        """删除空友爱看回复。
        
        OneBot 接口：``delete_qzone_public_reply``
        
        必填参数：
            feed (Any) —— 说说对象
            comment (Any) —— 附言
            reply (Any) —— 回复内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'delete_qzone_public_reply',
            feed=feed,
            comment=comment,
            reply=reply,
        )

    def do_group_album_comment(
        self,
        group_id: str,
        album_id: str,
        content: str,
        lloc: str = None,
        batch_id: str = None,
    ) -> Any:
        """发表群相册评论。
        
        OneBot 接口：``do_group_album_comment``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册 ID
            content (str) —— 评论内容
        
        可选参数：
            lloc (str, 默认 None) —— 图片 ID；不传或为空时评论整个上传批次，此时必须提供 batch_id
            batch_id (str, 默认 None) —— 上传批次 ID，可取自 get_group_album_media_list 返回的 batch.link_id 或 media[].batch_id
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'do_group_album_comment',
            group_id=group_id,
            album_id=album_id,
            lloc=lloc,
            batch_id=batch_id,
            content=content,
        )

    def download_file(
        self,
        url: str = None,
        base64: str = None,
        name: str = None,
        headers: list = None,
    ) -> Any:
        """下载文件。
        
        OneBot 接口：``download_file``
        
        可选参数：
            url (str, 默认 None) —— 下载链接
            base64 (str, 默认 None) —— base64数据
            name (str, 默认 None) —— 文件名
            headers (list, 默认 None) —— 请求头
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'download_file',
            url=url,
            base64=base64,
            name=name,
            headers=headers,
        )

    def download_file_image_stream(
        self,
        file: str = None,
        file_id: str = None,
        chunk_size: int = 64 * 1024,
    ) -> Any:
        """下载图片文件流。
        
        OneBot 接口：``download_file_image_stream``
        
        可选参数：
            file (str, 默认 None) —— 文件路径或 URL
            file_id (str, 默认 None) —— 文件 ID
            chunk_size (int, 默认 64 * 1024) —— 分块大小 (字节)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'download_file_image_stream',
            file=file,
            file_id=file_id,
            chunk_size=chunk_size,
        )

    def download_file_record_stream(
        self,
        file: str = None,
        file_id: str = None,
        chunk_size: int = 64 * 1024,
    ) -> Any:
        """下载语音文件流。
        
        OneBot 接口：``download_file_record_stream``
        
        可选参数：
            file (str, 默认 None) —— 文件路径或 URL
            file_id (str, 默认 None) —— 文件 ID
            chunk_size (int, 默认 64 * 1024) —— 分块大小 (字节)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'download_file_record_stream',
            file=file,
            file_id=file_id,
            chunk_size=chunk_size,
        )

    def download_file_stream(
        self,
        file: str = None,
        file_id: str = None,
        chunk_size: int = 64 * 1024,
    ) -> Any:
        """下载文件流。
        
        OneBot 接口：``download_file_stream``
        
        可选参数：
            file (str, 默认 None) —— 文件路径或 URL
            file_id (str, 默认 None) —— 文件 ID
            chunk_size (int, 默认 64 * 1024) —— 分块大小 (字节)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'download_file_stream',
            file=file,
            file_id=file_id,
            chunk_size=chunk_size,
        )

    def download_fileset(
        self,
        fileset_id: str,
    ) -> Any:
        """下载文件集。
        
        OneBot 接口：``download_fileset``
        
        必填参数：
            fileset_id (str) —— 文件集 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'download_fileset',
            fileset_id=fileset_id,
        )

    def fetch_custom_face(
        self,
        count: int = 48,
    ) -> Any:
        """获取自定义表情。
        
        OneBot 接口：``fetch_custom_face``
        
        可选参数：
            count (int, 默认 48) —— 获取数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'fetch_custom_face',
            count=count,
        )

    def fetch_custom_face_detail(
        self,
        count: int = 48,
    ) -> Any:
        """获取自定义表情详情。
        
        OneBot 接口：``fetch_custom_face_detail``
        
        可选参数：
            count (int, 默认 48) —— 获取数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'fetch_custom_face_detail',
            count=count,
        )

    def fetch_emoji_like(
        self,
        message_id: int,
        emojiId: int,
        emojiType: int,
        count: int = 20,
        cookie: str = '',
    ) -> Any:
        """获取表情点赞详情。
        
        OneBot 接口：``fetch_emoji_like``
        
        必填参数：
            message_id (int) —— 消息ID
            emojiId (int) —— 表情ID
            emojiType (int) —— 表情类型
        
        可选参数：
            count (int, 默认 20) —— 获取数量
            cookie (str, 默认 '') —— 分页Cookie
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'fetch_emoji_like',
            message_id=message_id,
            emojiId=emojiId,
            emojiType=emojiType,
            count=count,
            cookie=cookie,
        )

    def fetch_ptt_text(
        self,
        message_id: int,
    ) -> Any:
        """获取语音转文字结果。
        
        OneBot 接口：``fetch_ptt_text``
        
        必填参数：
            message_id (int) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'fetch_ptt_text',
            message_id=message_id,
        )

    def forward_friend_single_msg(
        self,
        message_id: int,
        group_id: str = None,
        user_id: str = None,
    ) -> Any:
        """转发单条消息给好友。
        
        OneBot 接口：``forward_friend_single_msg``
        
        必填参数：
            message_id (int) —— 消息ID
        
        可选参数：
            group_id (str, 默认 None) —— 目标群号
            user_id (str, 默认 None) —— 目标用户QQ
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'forward_friend_single_msg',
            message_id=message_id,
            group_id=group_id,
            user_id=user_id,
        )

    def forward_group_single_msg(
        self,
        message_id: int,
        group_id: str = None,
        user_id: str = None,
    ) -> Any:
        """转发单条消息到群。
        
        OneBot 接口：``forward_group_single_msg``
        
        必填参数：
            message_id (int) —— 消息ID
        
        可选参数：
            group_id (str, 默认 None) —— 目标群号
            user_id (str, 默认 None) —— 目标用户QQ
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'forward_group_single_msg',
            message_id=message_id,
            group_id=group_id,
            user_id=user_id,
        )

    def friend_poke(
        self,
        user_id: str,
        group_id: str = None,
        target_id: str = None,
    ) -> Any:
        """私聊戳一戳。
        
        OneBot 接口：``friend_poke``
        
        必填参数：
            user_id (str) —— 用户QQ
        
        可选参数：
            group_id (str, 默认 None) —— 群号
            target_id (str, 默认 None) —— 目标QQ
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'friend_poke',
            group_id=group_id,
            user_id=user_id,
            target_id=target_id,
        )

    def get_ai_characters(
        self,
        group_id: str,
        chat_type: int = 1,
    ) -> Any:
        """获取AI角色列表。
        
        OneBot 接口：``get_ai_characters``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            chat_type (int, 默认 1) —— 聊天类型
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_ai_characters',
            group_id=group_id,
            chat_type=chat_type,
        )

    def get_ai_record(
        self,
        character: str,
        group_id: str,
        text: str,
    ) -> Any:
        """获取 AI 语音。
        
        OneBot 接口：``get_ai_record``
        
        必填参数：
            character (str) —— 角色ID
            group_id (str) —— 群号
            text (str) —— 语音文本内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_ai_record',
            character=character,
            group_id=group_id,
            text=text,
        )

    def get_clientkey(
        self,
    ) -> Any:
        """获取ClientKey。
        
        OneBot 接口：``get_clientkey``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_clientkey',
        )

    def get_collection_list(
        self,
        category: str,
        count: str = '50',
    ) -> Any:
        """获取收藏列表。
        
        OneBot 接口：``get_collection_list``
        
        必填参数：
            category (str) —— 分类ID
        
        可选参数：
            count (str, 默认 '50') —— 获取数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_collection_list',
            category=category,
            count=count,
        )

    def get_cookies(
        self,
        domain: str,
    ) -> Any:
        """获取 Cookies。
        
        OneBot 接口：``get_cookies``
        
        必填参数：
            domain (str) —— 需要获取 cookies 的域名
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_cookies',
            domain=domain,
        )

    def get_credentials(
        self,
        domain: str,
    ) -> Any:
        """获取登录凭证。
        
        OneBot 接口：``get_credentials``
        
        必填参数：
            domain (str) —— 需要获取 cookies 的域名
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_credentials',
            domain=domain,
        )

    def get_csrf_token(
        self,
    ) -> Any:
        """获取 CSRF Token。
        
        OneBot 接口：``get_csrf_token``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_csrf_token',
        )

    def get_doubt_friends_add_request(
        self,
        count: int = 50,
    ) -> Any:
        """获取可疑好友申请。
        
        OneBot 接口：``get_doubt_friends_add_request``
        
        可选参数：
            count (int, 默认 50) —— 获取数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_doubt_friends_add_request',
            count=count,
        )

    def get_emoji_likes(
        self,
        message_id: str,
        emoji_id: str,
        group_id: str = None,
        emoji_type: str = None,
        count: int = 0,
    ) -> Any:
        """获取消息表情点赞列表。
        
        OneBot 接口：``get_emoji_likes``
        
        必填参数：
            message_id (str) —— 消息ID，可以传递长ID或短ID
            emoji_id (str) —— 表情ID
        
        可选参数：
            group_id (str, 默认 None) —— 群号，短ID可不传
            emoji_type (str, 默认 None) —— 表情类型
            count (int, 默认 0) —— 数量，0代表全部
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_emoji_likes',
            group_id=group_id,
            message_id=message_id,
            emoji_id=emoji_id,
            emoji_type=emoji_type,
            count=count,
        )

    def get_essence_msg_list(
        self,
        group_id: str,
    ) -> Any:
        """获取群精华消息。
        
        OneBot 接口：``get_essence_msg_list``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_essence_msg_list',
            group_id=group_id,
        )

    def get_file(
        self,
        file: str = None,
        file_id: str = None,
    ) -> Any:
        """获取文件。
        
        OneBot 接口：``get_file``
        
        可选参数：
            file (str, 默认 None) —— 文件路径、URL或Base64
            file_id (str, 默认 None) —— 文件ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_file',
            file=file,
            file_id=file_id,
        )

    def get_fileset_id(
        self,
        share_code: str,
    ) -> Any:
        """获取文件集 ID。
        
        OneBot 接口：``get_fileset_id``
        
        必填参数：
            share_code (str) —— 分享码或分享链接
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_fileset_id',
            share_code=share_code,
        )

    def get_fileset_info(
        self,
        fileset_id: str,
    ) -> Any:
        """获取文件集信息。
        
        OneBot 接口：``get_fileset_info``
        
        必填参数：
            fileset_id (str) —— 文件集 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_fileset_info',
            fileset_id=fileset_id,
        )

    def get_flash_file_list(
        self,
        fileset_id: str,
    ) -> Any:
        """获取闪传文件列表。
        
        OneBot 接口：``get_flash_file_list``
        
        必填参数：
            fileset_id (str) —— 文件集 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_flash_file_list',
            fileset_id=fileset_id,
        )

    def get_flash_file_url(
        self,
        fileset_id: str,
        file_name: str = None,
        file_index: int = None,
    ) -> Any:
        """获取闪传文件链接。
        
        OneBot 接口：``get_flash_file_url``
        
        必填参数：
            fileset_id (str) —— 文件集 ID
        
        可选参数：
            file_name (str, 默认 None) —— 文件名
            file_index (int, 默认 None) —— 文件索引
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_flash_file_url',
            fileset_id=fileset_id,
            file_name=file_name,
            file_index=file_index,
        )

    def get_forward_msg(
        self,
        message_id: str = None,
        id: str = None,
    ) -> Any:
        """获取合并转发消息。
        
        OneBot 接口：``get_forward_msg``
        
        可选参数：
            message_id (str, 默认 None) —— 消息ID
            id (str, 默认 None) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_forward_msg',
            message_id=message_id,
            id=id,
        )

    def get_friend_list(
        self,
        no_cache: bool = None,
    ) -> Any:
        """获取好友列表。
        
        OneBot 接口：``get_friend_list``
        
        可选参数：
            no_cache (bool, 默认 None) —— 是否不使用缓存
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_friend_list',
            no_cache=no_cache,
        )

    def get_friend_msg_history(
        self,
        user_id: str,
        message_seq: str = None,
        count: int = 20,
        reverse_order: bool = False,
        disable_get_url: bool = False,
        parse_mult_msg: bool = True,
        quick_reply: bool = False,
        reverseOrder: bool = False,
    ) -> Any:
        """获取好友历史消息。
        
        OneBot 接口：``get_friend_msg_history``
        
        必填参数：
            user_id (str) —— 用户QQ
        
        可选参数：
            message_seq (str, 默认 None) —— 起始消息序号
            count (int, 默认 20) —— 获取消息数量
            reverse_order (bool, 默认 False) —— 是否反向排序
            disable_get_url (bool, 默认 False) —— 是否禁用获取URL
            parse_mult_msg (bool, 默认 True) —— 是否解析合并消息
            quick_reply (bool, 默认 False) —— 是否快速回复
            reverseOrder (bool, 默认 False) —— 是否反向排序(旧版本兼容)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_friend_msg_history',
            user_id=user_id,
            message_seq=message_seq,
            count=count,
            reverse_order=reverse_order,
            disable_get_url=disable_get_url,
            parse_mult_msg=parse_mult_msg,
            quick_reply=quick_reply,
            reverseOrder=reverseOrder,
        )

    def get_friends_with_category(
        self,
    ) -> Any:
        """获取带分组的好友列表。
        
        OneBot 接口：``get_friends_with_category``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_friends_with_category',
        )

    def get_group_album_media_list(
        self,
        group_id: str,
        album_id: str,
        attach_info: str = '',
    ) -> Any:
        """获取群相册媒体列表。
        
        OneBot 接口：``get_group_album_media_list``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册ID
        
        可选参数：
            attach_info (str, 默认 '') —— 附加信息（用于分页）
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_album_media_list',
            group_id=group_id,
            album_id=album_id,
            attach_info=attach_info,
        )

    def get_group_at_all_remain(
        self,
        group_id: str,
    ) -> Any:
        """获取群艾特全体剩余次数。
        
        OneBot 接口：``get_group_at_all_remain``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_at_all_remain',
            group_id=group_id,
        )

    def get_group_detail_info(
        self,
        group_id: str,
    ) -> Any:
        """获取群详细信息。
        
        OneBot 接口：``get_group_detail_info``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_detail_info',
            group_id=group_id,
        )

    def get_group_file_system_info(
        self,
        group_id: str,
    ) -> Any:
        """获取群文件系统信息。
        
        OneBot 接口：``get_group_file_system_info``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_file_system_info',
            group_id=group_id,
        )

    def get_group_file_url(
        self,
        group_id: str,
        file_id: str,
    ) -> Any:
        """获取群文件URL。
        
        OneBot 接口：``get_group_file_url``
        
        必填参数：
            group_id (str) —— 群号
            file_id (str) —— 文件ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_file_url',
            group_id=group_id,
            file_id=file_id,
        )

    def get_group_files_by_folder(
        self,
        group_id: str,
        folder_id: str = None,
        folder: str = None,
        file_count: int = 50,
    ) -> Any:
        """获取群文件夹文件列表。
        
        OneBot 接口：``get_group_files_by_folder``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            folder_id (str, 默认 None) —— 文件夹ID
            folder (str, 默认 None) —— 文件夹ID
            file_count (int, 默认 50) —— 文件数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_files_by_folder',
            group_id=group_id,
            folder_id=folder_id,
            folder=folder,
            file_count=file_count,
        )

    def get_group_honor_info(
        self,
        group_id: str,
        type: Any = None,
    ) -> Any:
        """获取群荣誉信息。
        
        OneBot 接口：``get_group_honor_info``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            type (Any, 默认 None) —— 荣誉类型
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_honor_info',
            group_id=group_id,
            type=type,
        )

    def get_group_ignore_add_request(
        self,
    ) -> Any:
        """获取群被忽略的加群请求。
        
        OneBot 接口：``get_group_ignore_add_request``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_ignore_add_request',
        )

    def get_group_ignored_notifies(
        self,
    ) -> Any:
        """获取群忽略通知。
        
        OneBot 接口：``get_group_ignored_notifies``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_ignored_notifies',
        )

    def get_group_info(
        self,
        group_id: str,
    ) -> Any:
        """获取群信息。
        
        OneBot 接口：``get_group_info``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_info',
            group_id=group_id,
        )

    def get_group_info_ex(
        self,
        group_id: str,
    ) -> Any:
        """获取群详细信息 (扩展)。
        
        OneBot 接口：``get_group_info_ex``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_info_ex',
            group_id=group_id,
        )

    def get_group_list(
        self,
        no_cache: bool = None,
    ) -> Any:
        """获取群列表。
        
        OneBot 接口：``get_group_list``
        
        可选参数：
            no_cache (bool, 默认 None) —— 是否不使用缓存
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_list',
            no_cache=no_cache,
        )

    def get_group_member_info(
        self,
        group_id: str,
        user_id: str,
        no_cache: bool = None,
    ) -> Any:
        """获取群成员信息。
        
        OneBot 接口：``get_group_member_info``
        
        必填参数：
            group_id (str) —— 群号
            user_id (str) —— QQ号
        
        可选参数：
            no_cache (bool, 默认 None) —— 是否不使用缓存
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_member_info',
            group_id=group_id,
            user_id=user_id,
            no_cache=no_cache,
        )

    def get_group_member_list(
        self,
        group_id: str,
        no_cache: bool = None,
    ) -> Any:
        """获取群成员列表。
        
        OneBot 接口：``get_group_member_list``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            no_cache (bool, 默认 None) —— 是否不使用缓存
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_member_list',
            group_id=group_id,
            no_cache=no_cache,
        )

    def get_group_msg_history(
        self,
        group_id: str,
        message_seq: str = None,
        count: int = 20,
        reverse_order: bool = False,
        disable_get_url: bool = False,
        parse_mult_msg: bool = True,
        quick_reply: bool = False,
        reverseOrder: bool = False,
    ) -> Any:
        """获取群历史消息。
        
        OneBot 接口：``get_group_msg_history``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            message_seq (str, 默认 None) —— 起始消息序号
            count (int, 默认 20) —— 获取消息数量
            reverse_order (bool, 默认 False) —— 是否反向排序
            disable_get_url (bool, 默认 False) —— 是否禁用获取URL
            parse_mult_msg (bool, 默认 True) —— 是否解析合并消息
            quick_reply (bool, 默认 False) —— 是否快速回复
            reverseOrder (bool, 默认 False) —— 是否反向排序(旧版本兼容)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_msg_history',
            group_id=group_id,
            message_seq=message_seq,
            count=count,
            reverse_order=reverse_order,
            disable_get_url=disable_get_url,
            parse_mult_msg=parse_mult_msg,
            quick_reply=quick_reply,
            reverseOrder=reverseOrder,
        )

    def get_group_root_files(
        self,
        group_id: str,
        file_count: int = 50,
    ) -> Any:
        """获取群根目录文件列表。
        
        OneBot 接口：``get_group_root_files``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            file_count (int, 默认 50) —— 文件数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_root_files',
            group_id=group_id,
            file_count=file_count,
        )

    def get_group_share_link(
        self,
        group_id: int,
        need_short_url: bool = True,
        src_id: int = 73,
        additional_param: str = '',
    ) -> Any:
        """获取群分享链接。
        
        OneBot 接口：``get_group_share_link``
        
        必填参数：
            group_id (int) —— 群号
        
        可选参数：
            need_short_url (bool, 默认 True) —— 是否返回短链 (qm.qq.com/q/xxx)，false 返回完整 universal-share 链接
            src_id (int, 默认 73) —— 分享来源 ID
            additional_param (str, 默认 '') —— 附加参数
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_share_link',
            group_id=group_id,
            need_short_url=need_short_url,
            src_id=src_id,
            additional_param=additional_param,
        )

    def get_group_shut_list(
        self,
        group_id: str,
    ) -> Any:
        """获取群禁言列表。
        
        OneBot 接口：``get_group_shut_list``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_shut_list',
            group_id=group_id,
        )

    def get_group_signed_list(
        self,
        group_id: str,
    ) -> Any:
        """获取群组今日打卡列表。
        
        OneBot 接口：``get_group_signed_list``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_signed_list',
            group_id=group_id,
        )

    def get_group_system_msg(
        self,
        count: int = 50,
    ) -> Any:
        """获取群系统消息。
        
        OneBot 接口：``get_group_system_msg``
        
        可选参数：
            count (int, 默认 50) —— 获取的消息数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_group_system_msg',
            count=count,
        )

    def get_guild_list(
        self,
    ) -> Any:
        """获取频道列表。
        
        OneBot 接口：``get_guild_list``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_guild_list',
        )

    def get_guild_service_profile(
        self,
    ) -> Any:
        """获取频道个人信息。
        
        OneBot 接口：``get_guild_service_profile``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_guild_service_profile',
        )

    def get_image(
        self,
        file: str = None,
        file_id: str = None,
    ) -> Any:
        """获取图片。
        
        OneBot 接口：``get_image``
        
        可选参数：
            file (str, 默认 None) —— 文件路径、URL或Base64
            file_id (str, 默认 None) —— 文件ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_image',
            file=file,
            file_id=file_id,
        )

    def get_login_info(
        self,
    ) -> Any:
        """获取登录号信息。
        
        OneBot 接口：``get_login_info``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_login_info',
        )

    def get_mini_app_ark(
        self,
    ) -> Any:
        """获取小程序 Ark。
        
        OneBot 接口：``get_mini_app_ark``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_mini_app_ark',
        )

    def get_msg(
        self,
        message_id: int,
    ) -> Any:
        """获取消息。
        
        OneBot 接口：``get_msg``
        
        必填参数：
            message_id (int) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_msg',
            message_id=message_id,
        )

    def get_online_clients(
        self,
    ) -> Any:
        """获取在线客户端。
        
        OneBot 接口：``get_online_clients``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_online_clients',
        )

    def get_online_file_msg(
        self,
        user_id: str,
    ) -> Any:
        """获取在线文件消息。
        
        OneBot 接口：``get_online_file_msg``
        
        必填参数：
            user_id (str) —— 用户 QQ
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_online_file_msg',
            user_id=user_id,
        )

    def get_private_file_url(
        self,
        file_id: str,
    ) -> Any:
        """获取私聊文件URL。
        
        OneBot 接口：``get_private_file_url``
        
        必填参数：
            file_id (str) —— 文件ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_private_file_url',
            file_id=file_id,
        )

    def get_profile_like(
        self,
        user_id: str = None,
        start: int = 0,
        count: int = 10,
    ) -> Any:
        """获取资料点赞。
        
        OneBot 接口：``get_profile_like``
        
        可选参数：
            user_id (str, 默认 None) —— QQ号
            start (int, 默认 0) —— 起始位置
            count (int, 默认 10) —— 获取数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_profile_like',
            user_id=user_id,
            start=start,
            count=count,
        )

    def get_qun_album_list(
        self,
        group_id: str,
        attach_info: str = '',
    ) -> Any:
        """获取群相册列表。
        
        OneBot 接口：``get_qun_album_list``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            attach_info (str, 默认 '') —— 附加信息（用于分页，从上一次返回结果中获取）
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qun_album_list',
            group_id=group_id,
            attach_info=attach_info,
        )

    def get_qzone_comment_list(
        self,
        feed_ref: Any,
        cursor: Any,
    ) -> Any:
        """获取QQ空间说说评论。
        
        OneBot 接口：``get_qzone_comment_list``
        
        必填参数：
            feed_ref (Any) —— 说说引用
            cursor (Any) —— 翻页游标
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_comment_list',
            feed_ref=feed_ref,
            cursor=cursor,
        )

    def get_qzone_comment_replies(
        self,
        feed_ref: Any,
        comment: Any,
        cursor: Any,
    ) -> Any:
        """获取QQ空间评论楼中楼回复。
        
        OneBot 接口：``get_qzone_comment_replies``
        
        必填参数：
            feed_ref (Any) —— 说说引用
            comment (Any) —— 附言
            cursor (Any) —— 翻页游标
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_comment_replies',
            feed_ref=feed_ref,
            comment=comment,
            cursor=cursor,
        )

    def get_qzone_feeds(
        self,
        format: Any,
        cursor: Any,
        page_num: Any = None,
        count: Any = None,
    ) -> Any:
        """获取QQ空间好友动态。
        
        OneBot 接口：``get_qzone_feeds``
        
        必填参数：
            format (Any) —— 返回格式
            cursor (Any) —— 翻页游标
        
        可选参数：
            page_num (Any, 默认 None) —— 页码
            count (Any, 默认 None) —— 数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_feeds',
            format=format,
            page_num=page_num,
            count=count,
            cursor=cursor,
        )

    def get_qzone_msg_detail(
        self,
        feed_ref: Any = None,
        tid: Any = None,
        target_uin: Any = None,
        pos: Any = None,
        num: Any = None,
    ) -> Any:
        """获取QQ空间说说详情。
        
        OneBot 接口：``get_qzone_msg_detail``
        
        可选参数：
            feed_ref (Any, 默认 None) —— 说说引用
            tid (Any, 默认 None) —— 说说/消息 ID
            target_uin (Any, 默认 None) —— 目标 QQ
            pos (Any, 默认 None) —— 起始位置
            num (Any, 默认 None) —— 数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_msg_detail',
            feed_ref=feed_ref,
            tid=tid,
            target_uin=target_uin,
            pos=pos,
            num=num,
        )

    def get_qzone_msg_list(
        self,
        format: Any,
        cursor: Any,
        target_uin: Any = None,
        pos: Any = None,
        num: Any = None,
    ) -> Any:
        """获取QQ空间说说列表。
        
        OneBot 接口：``get_qzone_msg_list``
        
        必填参数：
            format (Any) —— 返回格式
            cursor (Any) —— 翻页游标
        
        可选参数：
            target_uin (Any, 默认 None) —— 目标 QQ
            pos (Any, 默认 None) —— 起始位置
            num (Any, 默认 None) —— 数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_msg_list',
            format=format,
            target_uin=target_uin,
            pos=pos,
            num=num,
            cursor=cursor,
        )

    def get_qzone_profile(
        self,
        target_uin: str = None,
    ) -> Any:
        """获取QQ空间资料。
        
        OneBot 接口：``get_qzone_profile``
        
        可选参数：
            target_uin (str, 默认 None) —— 空间所属 QQ 号；不传时为当前账号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_profile',
            target_uin=target_uin,
        )

    def get_qzone_public_capabilities(
        self,
    ) -> Any:
        """获取空友爱看接口能力。
        
        OneBot 接口：``get_qzone_public_capabilities``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_public_capabilities',
        )

    def get_qzone_public_comments(
        self,
        feed: Any,
        cursor: str,
    ) -> Any:
        """获取空友爱看评论。
        
        OneBot 接口：``get_qzone_public_comments``
        
        必填参数：
            feed (Any) —— 说说对象
            cursor (str) —— 动态详情或上一评论页返回的非空 attach_info；数字或布尔值会转为文本
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_public_comments',
            feed=feed,
            cursor=cursor,
        )

    def get_qzone_public_feed_detail(
        self,
        feed: Any,
    ) -> Any:
        """获取空友爱看动态详情。
        
        OneBot 接口：``get_qzone_public_feed_detail``
        
        必填参数：
            feed (Any) —— 说说对象
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_public_feed_detail',
            feed=feed,
        )

    def get_qzone_public_feeds(
        self,
        cursor: str = None,
    ) -> Any:
        """获取空友爱看动态。
        
        OneBot 接口：``get_qzone_public_feeds``
        
        可选参数：
            cursor (str, 默认 None) —— 上一页返回的非空 next_cursor，首次请求可省略；数字或布尔值会转为文本
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_public_feeds',
            cursor=cursor,
        )

    def get_qzone_public_replies(
        self,
        feed: Any,
        comment: Any,
        cursor: str = '',
        page_size: int = 20,
    ) -> Any:
        """获取空友爱看评论回复。
        
        OneBot 接口：``get_qzone_public_replies``
        
        必填参数：
            feed (Any) —— 说说对象
            comment (Any) —— 附言
        
        可选参数：
            cursor (str, 默认 '') —— 回复分页游标，默认为空字符串；空字符串时使用 comment.reply_attach_info；数字或布尔值会转为文本
            page_size (int, 默认 20) —— 每页回复数量，默认 20；有限数字或非空数值字符串，向零截断后应大于等于 1
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_qzone_public_replies',
            feed=feed,
            comment=comment,
            cursor=cursor,
            page_size=page_size,
        )

    def get_recent_contact(
        self,
        count: int = 10,
    ) -> Any:
        """获取最近会话。
        
        OneBot 接口：``get_recent_contact``
        
        可选参数：
            count (int, 默认 10) —— 获取的数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_recent_contact',
            count=count,
        )

    def get_record(
        self,
        out_format: str,
        file: str = None,
        file_id: str = None,
    ) -> Any:
        """获取语音。
        
        OneBot 接口：``get_record``
        
        必填参数：
            out_format (str) —— 输出格式
        
        可选参数：
            file (str, 默认 None) —— 文件路径、URL或Base64
            file_id (str, 默认 None) —— 文件ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_record',
            file=file,
            file_id=file_id,
            out_format=out_format,
        )

    def get_rkey(
        self,
    ) -> Any:
        """获取扩展 RKey。
        
        OneBot 接口：``get_rkey``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_rkey',
        )

    def get_rkey_server(
        self,
    ) -> Any:
        """获取 RKey 服务器。
        
        OneBot 接口：``get_rkey_server``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_rkey_server',
        )

    def get_robot_uin_range(
        self,
    ) -> Any:
        """获取机器人 UIN 范围。
        
        OneBot 接口：``get_robot_uin_range``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_robot_uin_range',
        )

    def get_share_link(
        self,
        fileset_id: str,
    ) -> Any:
        """获取文件分享链接。
        
        OneBot 接口：``get_share_link``
        
        必填参数：
            fileset_id (str) —— 文件集 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_share_link',
            fileset_id=fileset_id,
        )

    def get_status(
        self,
    ) -> Any:
        """获取运行状态。
        
        OneBot 接口：``get_status``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_status',
        )

    def get_stranger_info(
        self,
        user_id: str,
        no_cache: bool = False,
    ) -> Any:
        """获取陌生人信息。
        
        OneBot 接口：``get_stranger_info``
        
        必填参数：
            user_id (str) —— 用户QQ
        
        可选参数：
            no_cache (bool, 默认 False) —— 是否不使用缓存
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_stranger_info',
            user_id=user_id,
            no_cache=no_cache,
        )

    def get_unidirectional_friend_list(
        self,
    ) -> Any:
        """获取单向好友列表。
        
        OneBot 接口：``get_unidirectional_friend_list``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_unidirectional_friend_list',
        )

    def get_version_info(
        self,
    ) -> Any:
        """获取版本信息。
        
        OneBot 接口：``get_version_info``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'get_version_info',
        )

    def group_poke(
        self,
        user_id: str,
        group_id: str = None,
        target_id: str = None,
    ) -> Any:
        """群内戳一戳。
        
        OneBot 接口：``group_poke``
        
        必填参数：
            user_id (str) —— 用户QQ
        
        可选参数：
            group_id (str, 默认 None) —— 群号
            target_id (str, 默认 None) —— 目标QQ
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'group_poke',
            group_id=group_id,
            user_id=user_id,
            target_id=target_id,
        )

    def like_qzone(
        self,
        feed_ref: Any = None,
        tid: Any = None,
        target_uin: Any = None,
        abstime: Any = None,
    ) -> Any:
        """点赞QQ空间说说。
        
        OneBot 接口：``like_qzone``
        
        可选参数：
            feed_ref (Any, 默认 None) —— 说说引用
            tid (Any, 默认 None) —— 说说/消息 ID
            target_uin (Any, 默认 None) —— 目标 QQ
            abstime (Any, 默认 None) —— 绝对时间戳
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'like_qzone',
            feed_ref=feed_ref,
            tid=tid,
            target_uin=target_uin,
            abstime=abstime,
        )

    def mark_group_msg_as_read(
        self,
        user_id: str = None,
        group_id: str = None,
        message_id: str = None,
    ) -> Any:
        """标记群聊已读。
        
        OneBot 接口：``mark_group_msg_as_read``
        
        可选参数：
            user_id (str, 默认 None) —— 用户QQ
            group_id (str, 默认 None) —— 群号
            message_id (str, 默认 None) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'mark_group_msg_as_read',
            user_id=user_id,
            group_id=group_id,
            message_id=message_id,
        )

    def mark_msg_as_read(
        self,
        user_id: str = None,
        group_id: str = None,
        message_id: str = None,
    ) -> Any:
        """标记消息已读 (Go-CQHTTP)。
        
        OneBot 接口：``mark_msg_as_read``
        
        可选参数：
            user_id (str, 默认 None) —— 用户QQ
            group_id (str, 默认 None) —— 群号
            message_id (str, 默认 None) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'mark_msg_as_read',
            user_id=user_id,
            group_id=group_id,
            message_id=message_id,
        )

    def mark_private_msg_as_read(
        self,
        user_id: str = None,
        group_id: str = None,
        message_id: str = None,
    ) -> Any:
        """标记私聊已读。
        
        OneBot 接口：``mark_private_msg_as_read``
        
        可选参数：
            user_id (str, 默认 None) —— 用户QQ
            group_id (str, 默认 None) —— 群号
            message_id (str, 默认 None) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'mark_private_msg_as_read',
            user_id=user_id,
            group_id=group_id,
            message_id=message_id,
        )

    def move_group_file(
        self,
        group_id: str,
        file_id: str,
        current_parent_directory: str,
        target_parent_directory: str,
    ) -> Any:
        """移动群文件。
        
        OneBot 接口：``move_group_file``
        
        必填参数：
            group_id (str) —— 群号
            file_id (str) —— 文件ID
            current_parent_directory (str) —— 当前父目录
            target_parent_directory (str) —— 目标父目录
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'move_group_file',
            group_id=group_id,
            file_id=file_id,
            current_parent_directory=current_parent_directory,
            target_parent_directory=target_parent_directory,
        )

    def nc_get_packet_status(
        self,
    ) -> Any:
        """获取Packet状态。
        
        OneBot 接口：``nc_get_packet_status``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'nc_get_packet_status',
        )

    def nc_get_rkey(
        self,
    ) -> Any:
        """获取 RKey。
        
        OneBot 接口：``nc_get_rkey``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'nc_get_rkey',
        )

    def nc_get_user_status(
        self,
        user_id: str,
    ) -> Any:
        """获取用户在线状态。
        
        OneBot 接口：``nc_get_user_status``
        
        必填参数：
            user_id (str) —— QQ号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'nc_get_user_status',
            user_id=user_id,
        )

    def ocr_image(
        self,
        image: str,
    ) -> Any:
        """图片 OCR 识别。
        
        OneBot 接口：``ocr_image``
        
        必填参数：
            image (str) —— 图片路径、URL或Base64
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'ocr_image',
            image=image,
        )

    def receive_online_file(
        self,
        user_id: str,
        msg_id: str,
        element_id: str,
    ) -> Any:
        """接收在线文件。
        
        OneBot 接口：``receive_online_file``
        
        必填参数：
            user_id (str) —— 用户 QQ
            msg_id (str) —— 消息 ID
            element_id (str) —— 元素 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'receive_online_file',
            user_id=user_id,
            msg_id=msg_id,
            element_id=element_id,
        )

    def refuse_online_file(
        self,
        user_id: str,
        msg_id: str,
        element_id: str,
    ) -> Any:
        """拒绝在线文件。
        
        OneBot 接口：``refuse_online_file``
        
        必填参数：
            user_id (str) —— 用户 QQ
            msg_id (str) —— 消息 ID
            element_id (str) —— 元素 ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'refuse_online_file',
            user_id=user_id,
            msg_id=msg_id,
            element_id=element_id,
        )

    def rename_group_file(
        self,
        group_id: str,
        file_id: str,
        current_parent_directory: str,
        new_name: str,
    ) -> Any:
        """重命名群文件。
        
        OneBot 接口：``rename_group_file``
        
        必填参数：
            group_id (str) —— 群号
            file_id (str) —— 文件ID
            current_parent_directory (str) —— 当前父目录
            new_name (str) —— 新文件名
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'rename_group_file',
            group_id=group_id,
            file_id=file_id,
            current_parent_directory=current_parent_directory,
            new_name=new_name,
        )

    def reply_qzone_public_feed(
        self,
        feed: Any,
        comment: Any,
        content: Any,
        reply: Any = None,
    ) -> Any:
        """回复空友爱看评论。
        
        OneBot 接口：``reply_qzone_public_feed``
        
        必填参数：
            feed (Any) —— 说说对象
            comment (Any) —— 附言
            content (Any) —— 内容
        
        可选参数：
            reply (Any, 默认 None) —— 回复内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'reply_qzone_public_feed',
            feed=feed,
            comment=comment,
            content=content,
            reply=reply,
        )

    def send_ark_share(
        self,
        user_id: str = None,
        group_id: str = None,
        phone_number: str = '',
    ) -> Any:
        """发送 Ark 分享卡片。
        
        OneBot 接口：``send_ark_share``
        
        可选参数：
            user_id (str, 默认 None) —— QQ号
            group_id (str, 默认 None) —— 群号
            phone_number (str, 默认 '') —— 手机号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_ark_share',
            user_id=user_id,
            group_id=group_id,
            phone_number=phone_number,
        )

    def send_flash_msg(
        self,
        fileset_id: str,
        user_id: str = None,
        group_id: str = None,
    ) -> Any:
        """发送闪传消息。
        
        OneBot 接口：``send_flash_msg``
        
        必填参数：
            fileset_id (str) —— 文件集 ID
        
        可选参数：
            user_id (str, 默认 None) —— 用户 QQ
            group_id (str, 默认 None) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_flash_msg',
            fileset_id=fileset_id,
            user_id=user_id,
            group_id=group_id,
        )

    def send_forward_msg(
        self,
        message: Any,
        message_type: str = None,
        user_id: str = None,
        group_id: str = None,
        auto_escape: bool = None,
        news: dict = None,
        summary: str = None,
        prompt: str = None,
        timeout: int = None,
    ) -> Any:
        """发送合并转发消息。
        
        OneBot 接口：``send_forward_msg``
        
        必填参数：
            message (Any) —— 消息内容，支持字符串或消息段数组
        
        可选参数：
            message_type (str, 默认 None) —— 消息类型 (private/group)
            user_id (str, 默认 None) —— 用户QQ
            group_id (str, 默认 None) —— 群号
            auto_escape (bool, 默认 None) —— 是否作为纯文本发送
            news (dict, 默认 None) —— 合并转发新闻
            summary (str, 默认 None) —— 合并转发摘要
            prompt (str, 默认 None) —— 合并转发提示
            timeout (int, 默认 None) —— 自定义发送超时(毫秒)，覆盖自动计算值
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_forward_msg',
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
            message=message,
            auto_escape=auto_escape,
            news=news,
            summary=summary,
            prompt=prompt,
            timeout=timeout,
        )

    def send_group_ai_record(
        self,
        character: str,
        group_id: str,
        text: str,
    ) -> Any:
        """发送群 AI 语音。
        
        OneBot 接口：``send_group_ai_record``
        
        必填参数：
            character (str) —— 角色ID
            group_id (str) —— 群号
            text (str) —— 语音文本内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_group_ai_record',
            character=character,
            group_id=group_id,
            text=text,
        )

    def send_group_ark_share(
        self,
        group_id: str,
    ) -> Any:
        """发送群 Ark 分享卡片。
        
        OneBot 接口：``send_group_ark_share``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_group_ark_share',
            group_id=group_id,
        )

    def send_group_forward_msg(
        self,
        message: Any,
        message_type: str = None,
        user_id: str = None,
        group_id: str = None,
        auto_escape: bool = None,
        news: dict = None,
        summary: str = None,
        prompt: str = None,
        timeout: int = None,
    ) -> Any:
        """发送群合并转发消息。
        
        OneBot 接口：``send_group_forward_msg``
        
        必填参数：
            message (Any) —— 消息内容，支持字符串或消息段数组
        
        可选参数：
            message_type (str, 默认 None) —— 消息类型 (private/group)
            user_id (str, 默认 None) —— 用户QQ
            group_id (str, 默认 None) —— 群号
            auto_escape (bool, 默认 None) —— 是否作为纯文本发送
            news (dict, 默认 None) —— 合并转发新闻
            summary (str, 默认 None) —— 合并转发摘要
            prompt (str, 默认 None) —— 合并转发提示
            timeout (int, 默认 None) —— 自定义发送超时(毫秒)，覆盖自动计算值
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_group_forward_msg',
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
            message=message,
            auto_escape=auto_escape,
            news=news,
            summary=summary,
            prompt=prompt,
            timeout=timeout,
        )

    def send_group_msg(
        self,
        group_id: int,
        message: Any,
        random: Ref | None = None,
        req: Ref | None = None,
        auto_escape: bool = None,
        timeout: int = None,
    ) -> str:
        """发送群消息。
        
        OneBot 接口：``send_group_msg``
        
        成功时返回消息的 ``time``（字符串形式），用于撤回；失败返回空文本 ``""``。
        ``random``（message_seq）与 ``req``（real_id）会写回传入的 :class:`Ref` 对象。
        """
        try:
            data = self.call(
                'send_group_msg',
                group_id=group_id,
                message=message,
                auto_escape=auto_escape,
                timeout=timeout,
            ) or {}
        except QQBotError:
            if random is not None:
                random.value = 0
            if req is not None:
                req.value = 0
            return ""

        mid = (data or {}).get("message_id")
        if not mid:
            if random is not None:
                random.value = 0
            if req is not None:
                req.value = 0
            return ""

        t, seq, real = self._register_recall(mid)
        if random is not None:
            random.value = seq
        if req is not None:
            req.value = real
        return str(t)

    def send_group_sign(
        self,
        group_id: str,
    ) -> Any:
        """发送群签到。
        
        OneBot 接口：``send_group_sign``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_group_sign',
            group_id=group_id,
        )

    def send_like(
        self,
        user_id: str,
        times: int = 1,
    ) -> Any:
        """点赞。
        
        OneBot 接口：``send_like``
        
        必填参数：
            user_id (str) —— 对方 QQ 号
        
        可选参数：
            times (int, 默认 1) —— 点赞次数
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_like',
            user_id=user_id,
            times=times,
        )

    def send_msg(
        self,
        message: Any,
        message_type: str = None,
        user_id: str = None,
        group_id: str = None,
        auto_escape: bool = None,
        news: dict = None,
        summary: str = None,
        prompt: str = None,
        timeout: int = None,
    ) -> Any:
        """发送消息。
        
        OneBot 接口：``send_msg``
        
        必填参数：
            message (Any) —— 消息内容，支持字符串或消息段数组
        
        可选参数：
            message_type (str, 默认 None) —— 消息类型 (private/group)
            user_id (str, 默认 None) —— 用户QQ
            group_id (str, 默认 None) —— 群号
            auto_escape (bool, 默认 None) —— 是否作为纯文本发送
            news (dict, 默认 None) —— 合并转发新闻
            summary (str, 默认 None) —— 合并转发摘要
            prompt (str, 默认 None) —— 合并转发提示
            timeout (int, 默认 None) —— 自定义发送超时(毫秒)，覆盖自动计算值
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_msg',
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
            message=message,
            auto_escape=auto_escape,
            news=news,
            summary=summary,
            prompt=prompt,
            timeout=timeout,
        )

    def send_online_file(
        self,
        user_id: str,
        file_path: str,
        file_name: str = None,
    ) -> Any:
        """发送在线文件。
        
        OneBot 接口：``send_online_file``
        
        必填参数：
            user_id (str) —— 用户 QQ
            file_path (str) —— 本地文件路径
        
        可选参数：
            file_name (str, 默认 None) —— 文件名 (可选)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_online_file',
            user_id=user_id,
            file_path=file_path,
            file_name=file_name,
        )

    def send_online_folder(
        self,
        user_id: str,
        folder_path: str,
        folder_name: str = None,
    ) -> Any:
        """发送在线文件夹。
        
        OneBot 接口：``send_online_folder``
        
        必填参数：
            user_id (str) —— 用户 QQ
            folder_path (str) —— 本地文件夹路径
        
        可选参数：
            folder_name (str, 默认 None) —— 文件夹名称 (可选)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_online_folder',
            user_id=user_id,
            folder_path=folder_path,
            folder_name=folder_name,
        )

    def send_packet(
        self,
        cmd: str,
        data: str,
        rsp: str = True,
    ) -> Any:
        """发送原始数据包。
        
        OneBot 接口：``send_packet``
        
        必填参数：
            cmd (str) —— 命令字
            data (str) —— 十六进制数据
        
        可选参数：
            rsp (str, 默认 True) —— 是否等待响应
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_packet',
            cmd=cmd,
            data=data,
            rsp=rsp,
        )

    def send_poke(
        self,
        user_id: str,
        group_id: str = None,
        target_id: str = None,
    ) -> Any:
        """发送戳一戳。
        
        OneBot 接口：``send_poke``
        
        必填参数：
            user_id (str) —— 用户QQ
        
        可选参数：
            group_id (str, 默认 None) —— 群号
            target_id (str, 默认 None) —— 目标QQ
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_poke',
            group_id=group_id,
            user_id=user_id,
            target_id=target_id,
        )

    def send_private_forward_msg(
        self,
        message: Any,
        message_type: str = None,
        user_id: str = None,
        group_id: str = None,
        auto_escape: bool = None,
        news: dict = None,
        summary: str = None,
        prompt: str = None,
        timeout: int = None,
    ) -> Any:
        """发送私聊合并转发消息。
        
        OneBot 接口：``send_private_forward_msg``
        
        必填参数：
            message (Any) —— 消息内容，支持字符串或消息段数组
        
        可选参数：
            message_type (str, 默认 None) —— 消息类型 (private/group)
            user_id (str, 默认 None) —— 用户QQ
            group_id (str, 默认 None) —— 群号
            auto_escape (bool, 默认 None) —— 是否作为纯文本发送
            news (dict, 默认 None) —— 合并转发新闻
            summary (str, 默认 None) —— 合并转发摘要
            prompt (str, 默认 None) —— 合并转发提示
            timeout (int, 默认 None) —— 自定义发送超时(毫秒)，覆盖自动计算值
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_private_forward_msg',
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
            message=message,
            auto_escape=auto_escape,
            news=news,
            summary=summary,
            prompt=prompt,
            timeout=timeout,
        )

    def send_friend_msg(
        self,
        friend_qq: int,
        message: Any,
        random: Ref | None = None,
        req: Ref | None = None,
        auto_escape: bool = None,
        timeout: int = None,
    ) -> str:
        """发送私聊消息。
        
        OneBot 接口：``send_private_msg``
        
        成功时返回消息的 ``time``（字符串形式），用于撤回；失败返回空文本 ``""``。
        ``random``（message_seq）与 ``req``（real_id）会写回传入的 :class:`Ref` 对象。
        """
        try:
            data = self.call(
                'send_private_msg',
                user_id=friend_qq,
                message=message,
                auto_escape=auto_escape,
                timeout=timeout,
            ) or {}
        except QQBotError:
            if random is not None:
                random.value = 0
            if req is not None:
                req.value = 0
            return ""

        mid = (data or {}).get("message_id")
        if not mid:
            if random is not None:
                random.value = 0
            if req is not None:
                req.value = 0
            return ""

        t, seq, real = self._register_recall(mid)
        if random is not None:
            random.value = seq
        if req is not None:
            req.value = real
        return str(t)

    def send_qzone_msg(
        self,
        content: Any,
        images: list = None,
        ugc_right: int = 1,
        target_uins: list = None,
    ) -> Any:
        """发表QQ空间说说。
        
        OneBot 接口：``send_qzone_msg``
        
        必填参数：
            content (Any) —— 内容
        
        可选参数：
            images (list, 默认 None) —— 图片数组, 支持 file:// http(s):// base64:// , 自动上传
            ugc_right (int, 默认 1) —— 查看权限: 1所有人可见 4好友可见 16部分好友可见 64仅自己可见 128部分好友不可见
            target_uins (list, 默认 None) —— ugc_right为16/128时, 权限作用的QQ号数组
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'send_qzone_msg',
            content=content,
            images=images,
            ugc_right=ugc_right,
            target_uins=target_uins,
        )

    def set_custom_face_desc(
        self,
        emoji_id: int,
        res_id: str,
        md5: str,
        desc: str,
    ) -> Any:
        """修改自定义表情描述。
        
        OneBot 接口：``set_custom_face_desc``
        
        必填参数：
            emoji_id (int) —— 表情ID
            res_id (str) —— 资源ID
            md5 (str) —— 表情MD5
            desc (str) —— 新的表情描述
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_custom_face_desc',
            emoji_id=emoji_id,
            res_id=res_id,
            md5=md5,
            desc=desc,
        )

    def set_diy_online_status(
        self,
        face_id: int,
        wording: str = ' ',
    ) -> Any:
        """设置自定义在线状态。
        
        OneBot 接口：``set_diy_online_status``
        
        必填参数：
            face_id (int) —— 图标ID
        
        可选参数：
            wording (str, 默认 ' ') —— 状态文字内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_diy_online_status',
            face_id=face_id,
            wording=wording,
        )

    def set_doubt_friends_add_request(
        self,
        flag: str,
    ) -> Any:
        """处理可疑好友申请。
        
        OneBot 接口：``set_doubt_friends_add_request``
        
        必填参数：
            flag (str) —— 请求 flag
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_doubt_friends_add_request',
            flag=flag,
        )

    def set_essence_msg(
        self,
        message_id: int,
    ) -> Any:
        """设置精华消息。
        
        OneBot 接口：``set_essence_msg``
        
        必填参数：
            message_id (int) —— 消息ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_essence_msg',
            message_id=message_id,
        )

    def set_friend_add_request(
        self,
        flag: str,
        approve: str = None,
        remark: str = None,
    ) -> Any:
        """处理加好友请求。
        
        OneBot 接口：``set_friend_add_request``
        
        必填参数：
            flag (str) —— 加好友请求的 flag (需从上报中获取)
        
        可选参数：
            approve (str, 默认 None) —— 是否同意请求
            remark (str, 默认 None) —— 添加后的好友备注
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_friend_add_request',
            flag=flag,
            approve=approve,
            remark=remark,
        )

    def set_friend_remark(
        self,
        user_id: str,
        remark: str,
    ) -> Any:
        """设置好友备注。
        
        OneBot 接口：``set_friend_remark``
        
        必填参数：
            user_id (str) —— 对方 QQ 号
            remark (str) —— 备注内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_friend_remark',
            user_id=user_id,
            remark=remark,
        )

    def set_group_add_option(
        self,
        group_id: str,
        add_type: int,
        group_question: str = None,
        group_answer: str = None,
    ) -> Any:
        """设置群加群选项。
        
        OneBot 接口：``set_group_add_option``
        
        必填参数：
            group_id (str) —— 群号
            add_type (int) —— 加群方式
        
        可选参数：
            group_question (str, 默认 None) —— 加群问题
            group_answer (str, 默认 None) —— 加群答案
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_add_option',
            group_id=group_id,
            add_type=add_type,
            group_question=group_question,
            group_answer=group_answer,
        )

    def set_group_add_request(
        self,
        flag: str,
        approve: bool = None,
        reason: str = ' ',
        count: int = 100,
    ) -> Any:
        """处理加群请求。
        
        OneBot 接口：``set_group_add_request``
        
        必填参数：
            flag (str) —— 请求flag
        
        可选参数：
            approve (bool, 默认 None) —— 是否同意
            reason (str, 默认 ' ') —— 拒绝理由
            count (int, 默认 100) —— 搜索通知数量
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_add_request',
            flag=flag,
            approve=approve,
            reason=reason,
            count=count,
        )

    def set_group_admin(
        self,
        group_id: str,
        user_id: str,
        enable: bool = None,
    ) -> Any:
        """设置群管理员。
        
        OneBot 接口：``set_group_admin``
        
        必填参数：
            group_id (str) —— 群号
            user_id (str) —— 用户QQ
        
        可选参数：
            enable (bool, 默认 None) —— 是否设置为管理员
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_admin',
            group_id=group_id,
            user_id=user_id,
            enable=enable,
        )

    def set_group_album_media_like(
        self,
        group_id: str,
        album_id: str,
        batch_id: str,
        lloc: str = None,
    ) -> Any:
        """点赞群相册媒体。
        
        OneBot 接口：``set_group_album_media_like``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册ID
            batch_id (str) —— 批次 ID
        
        可选参数：
            lloc (str, 默认 None) —— lloc，若对整个上传操作则不填
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_album_media_like',
            group_id=group_id,
            album_id=album_id,
            batch_id=batch_id,
            lloc=lloc,
        )

    def set_group_ban(
        self,
        group_id: str,
        user_id: str,
        duration: int = 0,
    ) -> Any:
        """群组禁言。
        
        OneBot 接口：``set_group_ban``
        
        必填参数：
            group_id (str) —— 群号
            user_id (str) —— 用户QQ
        
        可选参数：
            duration (int, 默认 0) —— 禁言时长(秒)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_ban',
            group_id=group_id,
            user_id=user_id,
            duration=duration,
        )

    def set_group_card(
        self,
        group_id: str,
        user_id: str,
        card: str = None,
    ) -> Any:
        """设置群名片。
        
        OneBot 接口：``set_group_card``
        
        必填参数：
            group_id (str) —— 群号
            user_id (str) —— 用户QQ
        
        可选参数：
            card (str, 默认 None) —— 群名片
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_card',
            group_id=group_id,
            user_id=user_id,
            card=card,
        )

    def set_group_kick(
        self,
        group_id: str,
        user_id: str,
        reject_add_request: bool = None,
    ) -> Any:
        """群组踢人。
        
        OneBot 接口：``set_group_kick``
        
        必填参数：
            group_id (str) —— 群号
            user_id (str) —— 用户QQ
        
        可选参数：
            reject_add_request (bool, 默认 None) —— 是否拒绝加群请求
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_kick',
            group_id=group_id,
            user_id=user_id,
            reject_add_request=reject_add_request,
        )

    def set_group_kick_members(
        self,
        group_id: str,
        user_id: list,
        reject_add_request: bool = None,
    ) -> Any:
        """批量踢出群成员。
        
        OneBot 接口：``set_group_kick_members``
        
        必填参数：
            group_id (str) —— 群号
            user_id (list) —— QQ号列表
        
        可选参数：
            reject_add_request (bool, 默认 None) —— 是否拒绝加群请求
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_kick_members',
            group_id=group_id,
            user_id=user_id,
            reject_add_request=reject_add_request,
        )

    def set_group_leave(
        self,
        group_id: str,
        is_dismiss: bool = None,
    ) -> Any:
        """退出群组。
        
        OneBot 接口：``set_group_leave``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            is_dismiss (bool, 默认 None) —— 是否解散
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_leave',
            group_id=group_id,
            is_dismiss=is_dismiss,
        )

    def set_group_member_invite_policy(
        self,
        group_id: str,
        policy: Any,
    ) -> Any:
        """设置群成员邀请策略。
        
        OneBot 接口：``set_group_member_invite_policy``
        
        必填参数：
            group_id (str) —— 群号
            policy (Any) —— 策略
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_member_invite_policy',
            group_id=group_id,
            policy=policy,
        )

    def set_group_member_permissions(
        self,
        group_id: str,
        allow_member_upload_album: bool = None,
        allow_member_temporary_session: bool = None,
        allow_member_create_group: bool = None,
    ) -> Any:
        """设置群成员功能权限。
        
        OneBot 接口：``set_group_member_permissions``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            allow_member_upload_album (bool, 默认 None) —— 允许成员上传群相册
            allow_member_temporary_session (bool, 默认 None) —— 允许成员发起临时会话
            allow_member_create_group (bool, 默认 None) —— 允许成员发起新的群聊
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_member_permissions',
            group_id=group_id,
            allow_member_upload_album=allow_member_upload_album,
            allow_member_temporary_session=allow_member_temporary_session,
            allow_member_create_group=allow_member_create_group,
        )

    def set_group_name(
        self,
        group_id: str,
        group_name: str,
    ) -> Any:
        """设置群名称。
        
        OneBot 接口：``set_group_name``
        
        必填参数：
            group_id (str) —— 群号
            group_name (str) —— 群名称
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_name',
            group_id=group_id,
            group_name=group_name,
        )

    def set_group_new_member_history_visibility(
        self,
        group_id: str,
        visible: bool,
    ) -> Any:
        """设置新成员历史消息可见性。
        
        OneBot 接口：``set_group_new_member_history_visibility``
        
        必填参数：
            group_id (str) —— 群号
            visible (bool) —— 新成员默认可见最近聊天记录
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_new_member_history_visibility',
            group_id=group_id,
            visible=visible,
        )

    def set_group_portrait(
        self,
        file: str,
        group_id: str,
    ) -> Any:
        """设置群头像。
        
        OneBot 接口：``set_group_portrait``
        
        必填参数：
            file (str) —— 头像文件路径或 URL
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_portrait',
            file=file,
            group_id=group_id,
        )

    def set_group_remark(
        self,
        group_id: str,
        remark: str,
    ) -> Any:
        """设置群备注。
        
        OneBot 接口：``set_group_remark``
        
        必填参数：
            group_id (str) —— 群号
            remark (str) —— 备注
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_remark',
            group_id=group_id,
            remark=remark,
        )

    def set_group_robot_add_option(
        self,
        group_id: str,
        robot_member_switch: int = None,
        robot_member_examine: int = None,
    ) -> Any:
        """设置群机器人加群选项。
        
        OneBot 接口：``set_group_robot_add_option``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            robot_member_switch (int, 默认 None) —— 机器人成员开关
            robot_member_examine (int, 默认 None) —— 机器人成员审核
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_robot_add_option',
            group_id=group_id,
            robot_member_switch=robot_member_switch,
            robot_member_examine=robot_member_examine,
        )

    def set_group_search(
        self,
        group_id: str,
        no_code_finger_open: int = None,
        no_finger_open: int = None,
    ) -> Any:
        """设置群搜索选项。
        
        OneBot 接口：``set_group_search``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            no_code_finger_open (int, 默认 None) —— 未知
            no_finger_open (int, 默认 None) —— 未知
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_search',
            group_id=group_id,
            no_code_finger_open=no_code_finger_open,
            no_finger_open=no_finger_open,
        )

    def set_group_sign(
        self,
        group_id: str,
    ) -> Any:
        """群签到。
        
        OneBot 接口：``set_group_sign``
        
        必填参数：
            group_id (str) —— 群号
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_sign',
            group_id=group_id,
        )

    def set_group_special_title(
        self,
        group_id: str,
        user_id: str,
        special_title: str = '',
    ) -> Any:
        """设置专属头衔。
        
        OneBot 接口：``set_group_special_title``
        
        必填参数：
            group_id (str) —— 群号
            user_id (str) —— QQ号
        
        可选参数：
            special_title (str, 默认 '') —— 专属头衔
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_special_title',
            group_id=group_id,
            user_id=user_id,
            special_title=special_title,
        )

    def set_group_todo(
        self,
        group_id: str,
        message_id: str = None,
        message_seq: str = None,
    ) -> Any:
        """设置群待办。
        
        OneBot 接口：``set_group_todo``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            message_id (str, 默认 None) —— 消息ID
            message_seq (str, 默认 None) —— 消息Seq (可选)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_todo',
            group_id=group_id,
            message_id=message_id,
            message_seq=message_seq,
        )

    def set_group_whole_ban(
        self,
        group_id: str,
        enable: bool = None,
    ) -> Any:
        """全员禁言。
        
        OneBot 接口：``set_group_whole_ban``
        
        必填参数：
            group_id (str) —— 群号
        
        可选参数：
            enable (bool, 默认 None) —— 是否开启全员禁言
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_group_whole_ban',
            group_id=group_id,
            enable=enable,
        )

    def set_input_status(
        self,
        user_id: str,
        event_type: int,
    ) -> Any:
        """设置输入状态。
        
        OneBot 接口：``set_input_status``
        
        必填参数：
            user_id (str) —— QQ号
            event_type (int) —— 事件类型
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_input_status',
            user_id=user_id,
            event_type=event_type,
        )

    def set_msg_emoji_like(
        self,
        message_id: int,
        emoji_id: int,
        set: bool = None,
    ) -> Any:
        """设置消息表情点赞。
        
        OneBot 接口：``set_msg_emoji_like``
        
        必填参数：
            message_id (int) —— 消息ID
            emoji_id (int) —— 表情ID
        
        可选参数：
            set (bool, 默认 None) —— 是否设置
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_msg_emoji_like',
            message_id=message_id,
            emoji_id=emoji_id,
            set=set,
        )

    def set_online_status(
        self,
        status: int,
        ext_status: int,
        battery_status: int,
    ) -> Any:
        """设置在线状态。
        
        OneBot 接口：``set_online_status``
        
        必填参数：
            status (int) —— 在线状态
            ext_status (int) —— 扩展状态
            battery_status (int) —— 电量状态
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_online_status',
            status=status,
            ext_status=ext_status,
            battery_status=battery_status,
        )

    def set_qq_avatar(
        self,
        file: str,
    ) -> Any:
        """设置QQ头像。
        
        OneBot 接口：``set_qq_avatar``
        
        必填参数：
            file (str) —— 图片路径、URL或Base64
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qq_avatar',
            file=file,
        )

    def set_qq_profile(
        self,
        nickname: str,
        personal_note: str = None,
        sex: int = None,
    ) -> Any:
        """设置QQ资料。
        
        OneBot 接口：``set_qq_profile``
        
        必填参数：
            nickname (str) —— 昵称
        
        可选参数：
            personal_note (str, 默认 None) —— 个性签名
            sex (int, 默认 None) —— 性别 (0: 未知, 1: 男, 2: 女)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qq_profile',
            nickname=nickname,
            personal_note=personal_note,
            sex=sex,
        )

    def set_qzone_ban(
        self,
        user_id: str,
        enable: bool = None,
    ) -> Any:
        """设置QQ空间访问限制。
        
        OneBot 接口：``set_qzone_ban``
        
        必填参数：
            user_id (str) —— 需要设置空间访问限制的QQ号
        
        可选参数：
            enable (bool, 默认 None) —— 默认true；支持布尔值及true/false、1/0、yes/no、on/off拼写
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qzone_ban',
            user_id=user_id,
            enable=enable,
        )

    def set_qzone_msg_right(
        self,
        tid: Any,
        ugc_right: int,
        target_uins: list = None,
    ) -> Any:
        """修改QQ空间说说权限。
        
        OneBot 接口：``set_qzone_msg_right``
        
        必填参数：
            tid (Any) —— 说说/消息 ID
            ugc_right (int) —— 查看权限：1所有人，4好友，16部分好友，64仅自己，128排除部分好友
        
        可选参数：
            target_uins (list, 默认 None) —— ugc_right 为16或128时的QQ号列表
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qzone_msg_right',
            tid=tid,
            ugc_right=ugc_right,
            target_uins=target_uins,
        )

    def set_qzone_profile(
        self,
        name: Any = None,
        description: Any = None,
    ) -> Any:
        """修改QQ空间资料。
        
        OneBot 接口：``set_qzone_profile``
        
        可选参数：
            name (Any, 默认 None) —— 名称
            description (Any, 默认 None) —— 描述
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qzone_profile',
            name=name,
            description=description,
        )

    def set_qzone_public_comment_like(
        self,
        feed: Any,
        comment: Any,
        enable: Any,
        reply: Any = None,
    ) -> Any:
        """设置空友爱看评论或回复赞。
        
        OneBot 接口：``set_qzone_public_comment_like``
        
        必填参数：
            feed (Any) —— 说说对象
            comment (Any) —— 附言
            enable (Any) —— 是否启用
        
        可选参数：
            reply (Any, 默认 None) —— 回复内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qzone_public_comment_like',
            feed=feed,
            comment=comment,
            reply=reply,
            enable=enable,
        )

    def set_qzone_public_follow(
        self,
        feed: Any,
        enable: Any,
    ) -> Any:
        """蹲或取消蹲空友爱看作者。
        
        OneBot 接口：``set_qzone_public_follow``
        
        必填参数：
            feed (Any) —— 说说对象
            enable (Any) —— 是否启用
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qzone_public_follow',
            feed=feed,
            enable=enable,
        )

    def set_qzone_public_like(
        self,
        feed: Any,
        enable: Any,
    ) -> Any:
        """设置空友爱看普通赞。
        
        OneBot 接口：``set_qzone_public_like``
        
        必填参数：
            feed (Any) —— 说说对象
            enable (Any) —— 是否启用
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qzone_public_like',
            feed=feed,
            enable=enable,
        )

    def set_qzone_public_upvote(
        self,
        feed: Any,
        enable: Any,
    ) -> Any:
        """推或取消推空友爱看动态。
        
        OneBot 接口：``set_qzone_public_upvote``
        
        必填参数：
            feed (Any) —— 说说对象
            enable (Any) —— 是否启用
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_qzone_public_upvote',
            feed=feed,
            enable=enable,
        )

    def set_restart(
        self,
    ) -> Any:
        """重启服务。
        
        OneBot 接口：``set_restart``
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_restart',
        )

    def set_self_longnick(
        self,
        longNick: str,
    ) -> Any:
        """设置个性签名。
        
        OneBot 接口：``set_self_longnick``
        
        必填参数：
            longNick (str) —— 签名内容
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'set_self_longnick',
            longNick=longNick,
        )

    def test_download_stream(
        self,
        error: bool = False,
    ) -> Any:
        """测试下载流。
        
        OneBot 接口：``test_download_stream``
        
        可选参数：
            error (bool, 默认 False) —— 是否触发测试错误
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'test_download_stream',
            error=error,
        )

    def trans_group_file(
        self,
        group_id: str,
        file_id: str,
    ) -> Any:
        """传输群文件。
        
        OneBot 接口：``trans_group_file``
        
        必填参数：
            group_id (str) —— 群号
            file_id (str) —— 文件ID
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'trans_group_file',
            group_id=group_id,
            file_id=file_id,
        )

    def translate_en2zh(
        self,
        words: list,
    ) -> Any:
        """英文单词翻译。
        
        OneBot 接口：``translate_en2zh``
        
        必填参数：
            words (list) —— 待翻译单词列表
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'translate_en2zh',
            words=words,
        )

    def unlike_qzone(
        self,
        feed_ref: Any = None,
        tid: Any = None,
        target_uin: Any = None,
        abstime: Any = None,
    ) -> Any:
        """取消QQ空间说说点赞。
        
        OneBot 接口：``unlike_qzone``
        
        可选参数：
            feed_ref (Any, 默认 None) —— 说说引用
            tid (Any, 默认 None) —— 说说/消息 ID
            target_uin (Any, 默认 None) —— 目标 QQ
            abstime (Any, 默认 None) —— 绝对时间戳
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'unlike_qzone',
            feed_ref=feed_ref,
            tid=tid,
            target_uin=target_uin,
            abstime=abstime,
        )

    def upload_file_stream(
        self,
        stream_id: str,
        chunk_data: str = None,
        chunk_index: int = None,
        total_chunks: int = None,
        file_size: int = None,
        expected_sha256: str = None,
        is_complete: bool = None,
        filename: str = None,
        reset: bool = None,
        verify_only: bool = None,
        file_retention: int = 300 * 1e3,
    ) -> Any:
        """上传文件流。
        
        OneBot 接口：``upload_file_stream``
        
        必填参数：
            stream_id (str) —— 流 ID
        
        可选参数：
            chunk_data (str, 默认 None) —— 分块数据 (Base64)
            chunk_index (int, 默认 None) —— 分块索引
            total_chunks (int, 默认 None) —— 总分块数
            file_size (int, 默认 None) —— 文件总大小
            expected_sha256 (str, 默认 None) —— 期望的 SHA256
            is_complete (bool, 默认 None) —— 是否完成
            filename (str, 默认 None) —— 文件名
            reset (bool, 默认 None) —— 是否重置
            verify_only (bool, 默认 None) —— 是否仅验证
            file_retention (int, 默认 300 * 1e3) —— 文件保留时间 (毫秒)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'upload_file_stream',
            stream_id=stream_id,
            chunk_data=chunk_data,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            file_size=file_size,
            expected_sha256=expected_sha256,
            is_complete=is_complete,
            filename=filename,
            reset=reset,
            verify_only=verify_only,
            file_retention=file_retention,
        )

    def upload_group_file(
        self,
        group_id: str,
        file: str,
        name: str,
        folder: str = None,
        folder_id: str = None,
    ) -> Any:
        """上传群文件。
        
        OneBot 接口：``upload_group_file``
        
        必填参数：
            group_id (str) —— 群号
            file (str) —— 资源路径或URL
            name (str) —— 文件名
        
        可选参数：
            folder (str, 默认 None) —— 父目录 ID
            folder_id (str, 默认 None) —— 父目录 ID (兼容性字段)
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'upload_group_file',
            group_id=group_id,
            file=file,
            name=name,
            folder=folder,
            folder_id=folder_id,
        )

    def upload_image_to_qun_album(
        self,
        group_id: str,
        album_id: str,
        album_name: str,
        file: str,
    ) -> Any:
        """上传图片到群相册。
        
        OneBot 接口：``upload_image_to_qun_album``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册ID
            album_name (str) —— 相册名称
            file (str) —— 图片路径、URL或Base64
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'upload_image_to_qun_album',
            group_id=group_id,
            album_id=album_id,
            album_name=album_name,
            file=file,
        )

    def upload_images_to_qun_album(
        self,
        group_id: str,
        album_id: str,
        album_name: str,
        files: list,
    ) -> Any:
        """上传多张图片到群相册。
        
        OneBot 接口：``upload_images_to_qun_album``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册ID
            album_name (str) —— 相册名称
            files (list) —— 图片路径、URL或Base64 数组，一次上传多张
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'upload_images_to_qun_album',
            group_id=group_id,
            album_id=album_id,
            album_name=album_name,
            files=files,
        )

    def upload_private_file(
        self,
        user_id: str,
        file: str,
        name: str,
        upload_file: bool = True,
    ) -> Any:
        """上传私聊文件。
        
        OneBot 接口：``upload_private_file``
        
        必填参数：
            user_id (str) —— 用户 QQ
            file (str) —— 资源路径或URL
            name (str) —— 文件名
        
        可选参数：
            upload_file (bool, 默认 True) —— 是否执行上传
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'upload_private_file',
            user_id=user_id,
            file=file,
            name=name,
            upload_file=upload_file,
        )

    def upload_video_to_qun_album(
        self,
        group_id: str,
        album_id: str,
        album_name: str,
        file: str,
    ) -> Any:
        """上传视频到群相册。
        
        OneBot 接口：``upload_video_to_qun_album``
        
        必填参数：
            group_id (str) —— 群号
            album_id (str) —— 相册ID
            album_name (str) —— 相册名称
            file (str) —— 视频路径、URL或Base64
        
        返回值：接口 ``data`` 字段的内容。
        """
        return self.call(
            'upload_video_to_qun_album',
            group_id=group_id,
            album_id=album_id,
            album_name=album_name,
            file=file,
        )

    # ------------------------------------------------------------------ #
    # 易语言风格的撤回包装
    # ------------------------------------------------------------------ #
    def recall_friend_msg(self, time: int, random: int = 0, req: int = 0) -> bool:
        """按 :meth:`send_friend_msg` 返回的三元组撤回。"""
        return self.recall(time=time, random=random, req=req)

    def recall_group_msg(self, time: int, random: int = 0, req: int = 0) -> bool:
        """按 :meth:`send_group_msg` 返回的三元组撤回。"""
        return self.recall(time=time, random=random, req=req)

