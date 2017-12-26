#!/usr/bin/env python
# -*- coding:utf-8 -*-
#项目启动文件
from ihome import create_app, db
from flask_script import Manager
from flask_migrate import Migrate, MigrateCommand
from ihome import models

app = create_app("development")

Migrate(app, db)
manager = Manager(app)
manager.add_command("db", MigrateCommand)


if __name__ == '__main__':
    print app.url_map
    manager.run()

