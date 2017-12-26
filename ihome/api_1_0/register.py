# coding:utf-8
from flask import current_app, jsonify, make_response, request, session
# 导入蓝图api
from . import api
# 导入captcha扩展
from ihome.utils.captcha.captcha import captcha

# 导入redis数据库
from ihome import redis_store
from ihome import constants
from ihome.utils.response_code import RET
from ihome.utils import sms
from ihome.models import User
import re
import random
from manage import db


@api.route('/imagecode/<image_code_id>', methods=['GET'])
def generate_image_code(image_code_id):
    """
    生成图片验证码
    1.调用captcha扩展，生成图片验证码， name，text，image
    2.存储图片验证码，保存在redis中
    3.返回前端图片验证码，设置响应数据类型
    :param image_code_id:
    :return:
    """
    # 调用扩展，生成图片验证码
    name, text, image = captcha.generate_captcha()
    # 调用redis数据库，存储图片验证码内容
    try:
        redis_store.setex('ImageCode_' + image_code_id,constants.IMAGE_CODE_REDIS_EXPIRES, text)
    except Exception as e:
        # 记录错误的日志
        current_app.logger.error(e)
        # 返回前端错误信息
        return jsonify(errno=RET.DBERR, errmsg='保存图片验证码失败')
    else:
        # 返回图片
        response = make_response(image)
        response.headers['Content-Type'] = 'image/jpg'
        return response


@api.route('/smscode/<mobile>', methods=['GET'])
def send_sms_code(mobile):
    """
    1/获取参数,mobile,text,id,request.args.get('text')
    2/校验参数的完整性
    3/校验手机号,正则表达式校验手机号格式
    4/校验图片验证码,操作redis数据库,获取本地存储的真实图片验证码
    5/校验获取结果,判断真实的图片验证码是否存在
    6/删除redis中的图片验证码
    7/比较图片验证码是否一致
    8/生成短信验证码,'%06d' % random.randint(1,999999)生成随机数
    9/在本地存储短信验证码,存redis中
    10/判断手机号是否已注册
    11调用云通讯接口,发送短信,send_template_sms(mobile,sms_coce,time,tempID)
    12/保存发送结果,判断发送是否成功
    13/返回结果
    :param mobile:
    :return:
    """
    # 获取参数
    image_code = request.args.get('text')
    image_code_id = request.args.get('id')
    # 校验参数的完整性
    if not all([mobile, image_code_id, image_code]):
        return jsonify(errno=RET.PARAMERR, errmsg='参数不完整')
    # 校验手机号码的格式
    if not re.match(r'1[3456789]\d{9}', mobile):
        return jsonify(errno=RET.PARAMERR, errmsg='手机号码格式不正确')
    # 校验图片验证码，从redis中获取
    try:
        real_image_code = redis_store.get('ImageCode_' + image_code_id)
    except Exception as e:
        # 写入日志文件
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='获取图片验证码失败')
    # 校验获取结果
    if not real_image_code:
        return jsonify(errno=RET.NODATA, errmsg='图片验证码失效')
    # 删除图片验证码
    try:
        redis_store.delete('ImageCode_' + image_code_id)
    except Exception as e:
        # 写入日志文件
        current_app.logger.error(e)

    # 比较图片验证码是否一致，并忽略大小写
    if real_image_code.lower() != image_code.lower():
        return jsonify(errno=RET.PARAMERR, errmsg='图片验证码错误')

    # 开始准备发送短信验证码
    sms_code = '%06d'% random.randint(1, 999999)
    # 把验证码保存到redis中
    try:
        redis_store.setex('SMSCode_' + mobile,constants.SMS_CODE_REDIS_EXPIRES,sms_code)

    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='保存短信验证码失败')

    # 判断手机号是否已经注册
    try:
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='获取用户的信息失败')
    else:
        # 判断用户是否已经存在
        if user is not None:
            return jsonify(errno=RET.DATAEXIS,errmsg='用户已经存在')

    # 调用云通讯接口发送短信
    try:
        cpp = sms.CCP()
        # 发送短信的模板方法会有返回值，0 表示发送成功
        result = cpp.send_template_sms(mobile, [sms_code, constants.SMS_CODE_REDIS_EXPIRES/60], 1)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR, errmsg='发送短信异常')

    # 判断发送结果
    if 0 == result:
        return jsonify(errno=RET.OK, errmsg='发送成功')
    else:
        return jsonify(errno=RET.THIRDERR, errmsg='发送失败')


@api.route('/users', methods=['POST'])
def register():
    """
    注册
    1/获取参数,使用user_data = request.get_json()
    2/校验参数的存在
    3/进一步获取详细的参数信息,mobile,smscode,password
    4/校验参数的完整性
    5/进一步校验详细的参数信息,mobile
    6/校验短信验证码,获取本地存储的短信验证码
    7/判断短信验证码是否过期
    8/比较短信验证码是否正确
    9/删除短信验证码
    10/判断用户是否已注册
    11/保存用户信息,
    user = User(mobile=mobile,name=mobile)
    user.password = password
    12/缓存用户信息:flask_session扩展包的作用:指定用户的缓存信息存放位置,加密签名,指定有效期;
    我们需要使用请求上下文对象session来从redis中获取或设置用户信息;
    session.get('user_id')
    session[user_id] = user_id
    13/返回结果
    :return:
    """
    # 获取参数
    user_data = request.get_json()
    # 判断获取结果
    if not user_data:
        return jsonify(errno=RET.PARAMERR, errmsg='参数缺失')

    # 进一步获取详细的参数信息
    mobile = user_data.get('mobile')
    smscode = user_data.get('sms_code')
    password = user_data.get('password')
    # 校验参数的完整性
    if not all([mobile, smscode, password]):
        return jsonify(errno=RET.PARAMERR, errmsg='参数不完整')

    # 校验手机号格式是否符合要求
    if not re.match(r'1[3456789]\d{9}$', mobile):
        return jsonify(errno=RET.PARAMERR, errmsg='手机号格式错误')

    # 校验短信验证码,从redis中获取真实的短信验证码
    try:
        real_sms_code = redis_store.get('SMSCode_' + mobile)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='查询短信验证码失败')
    # 判断获取结果
    if not real_sms_code:
        return jsonify(errno=RET.NODATA, errmsg='短信验证码过期')
    # 比较短信验证码
    if real_sms_code != str(smscode):
        return jsonify(errno=RET.DATAERR, errmsg='短信验证码错误')

    # 删除短信验证码
    try:
        redis_store.delete('SMSCode_' + mobile)
    except Exception as e:
        current_app.logger.error(e)

    # 判断用户是否已注册
    try:
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='查询用户信息异常')
    else:
        if user is not None:
            return jsonify(errno=RET.DATAEXIST, errmsg='手机号已注册')



    # 调用模型类对象，保存用户信息
    user = User(mobile=mobile, name=mobile)
    # 对密码存储,这里调用了模型类generate_password_hash方法,对密码进行加密存储
    user.password = password

    # 提交数据到数据库中
    try:
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        # 存入数据如果发生异常,需要进行回滚
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg='保存用户信息失败')

    # 缓存用户的信息，使用请求上下文对象session
    session['user_id'] = user.id
    session['name'] = mobile
    session['mobile'] = mobile

    # 返回结果，data 为附属消息
    return jsonify(errno=RET.OK, errmsg='OK', data=user.to_dict())