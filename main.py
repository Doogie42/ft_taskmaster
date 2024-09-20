import yaml

import queue
import logging

from Poller import Poller
from MyProcess import MyProcess
from Task import Task

from taskmasterctl.server_http import launch_server

logger = logging.getLogger(__name__)

TIMEOUT = 0.01

import gc
import sys

from taskmasterctl.MyQueue import MyQueue

from ProcessManager import ProcessManager
from HttpBuffer import HttpBuffer

# When do we despawn all process:
    # -> process name change
    # -> cmd / workingdir / env / umask
    # numproc goes down
# We dont spawn / despawn process:
    # -> autostart / autorestart / exit code / start retries / stopsignal
    # -> stopwaitsec / stodut / stderr

# We spawn new process 
#    -> numproc goes up

# We 'clear' process history if we have a change
# if we already have 2 restart failed and we change stdout -> we set nb of restart failed to 0

# if we have the same config we do nothing

def get_fd():
    lsof_path = shutil.which("lsof")
    if lsof_path is None:
        raise NotImplementedError("Didn't handle unavailable lsof.")
    raw_procs = subprocess.check_output(
        [lsof_path, "-w", "-Ff", "-p", str(os.getpid())]
    )

    def filter_fds(lsof_entry: str) -> bool:
        return lsof_entry.startswith("f") and lsof_entry[1:].isdigit()

    fds = list(filter(filter_fds, raw_procs.decode().split(os.linesep)))
    print(fds, len(fds))


def get_task_from_config_file(config_name):
    with open(config_name, 'r') as file:
        config = yaml.safe_load(file)
    task_list = {}
    for task_name, config in config["programs"].items():
        task_list[task_name] = Task(task_name, config)
    return task_list


def reload_conf(config_name, process_manager, old_task_list, poller):
    new_task_list = get_task_from_config_file(config_name)
    for old_task_name, old_task in old_task_list.items():
        # this task not in new config => despawn
        if not old_task_name in new_task_list:
            process_manager.stop_process_from_task(old_task)
            continue
        # exact same config => we do nothing
        if old_task == new_task_list[old_task_name]:
            continue
        # if we need a full despawn / respawn:
        if old_task.need_despawn(new_task_list[old_task_name]):
            process_manager.stop_process_from_task(old_task)
            process_manager.create_process_from_task_reload(new_task_list[old_task_name])
            continue
        
        # we need to add process because numproc went up
        if old_task.numproc_went_up(new_task_list[old_task_name]):
            process_manager.add_process_numproc_up(old_task, new_task_list[old_task_name])
        # last case no need to respawn we need to update process config 
        # -> we might have a *small* window of time where process continue with old config
        process_manager.update_process_from_task(new_task_list[old_task_name])

    # new task in new config to spawn
    for new_task_name, new_task in new_task_list.items():
        if new_task_name not in old_task_list:
            process_manager.create_process_from_task(new_task)
            process_manager.start_process_from_task(new_task)
    
    process_manager.register_process(poller)

    return new_task_list



def handle_cmd(cmd, process, process_manager, poller, task_list):
    if cmd == "stop":
        if process != "all":
            process_manager.stop_process(process)
        else:
            process_manager.stop_all(poller)
        HttpBuffer.put_msg(process_manager.get_all_state())
    elif cmd == "start":
        if process != "all":
            process_manager.start_process(process, poller)
        else:
            process_manager.start_all_process(poller)

        HttpBuffer.put_msg(process_manager.get_all_state())
    elif cmd == "restart":
        process_manager.restart_process(process)
        HttpBuffer.put_msg(process_manager.get_all_state())
    elif cmd == "status":
        HttpBuffer.put_msg(process_manager.get_all_state())
        get_fd()
    elif cmd == "update":
        task_list = reload_conf('config_test.yml', process_manager,
                                task_list, poller)
    
        HttpBuffer.put_msg(process_manager.get_all_state())
    elif cmd == "attach":
        process_manager.attach(process)
        HttpBuffer.put_msg(process_manager.get_all_state())

    elif cmd == "detach":
        process_manager.detach(process)
        HttpBuffer.put_msg(process_manager.get_all_state())

    elif cmd == "attach_cmd":
        process_manager.send_attached(process)

    return task_list

def main():

    logging.basicConfig(level=logging.INFO)
    launch_server(int (sys.argv[1]))
    task_list = get_task_from_config_file('config_test.yml')
    q = MyQueue
    poller = Poller()

    process_manager = ProcessManager(q)
    for _, task in task_list.items():
        process_manager.create_process_from_task(task)

    process_manager.start_all_process(poller, first_launch=True)
    
    do_reload = 0
    while True:
        try:
            item = q.get(timeout=TIMEOUT)
            if item[0] == "DEAD":
                process_manager.handle_process_stopped(item[1], poller)
            elif item[0] == "DELETEME":
                process_manager.forget_process(item[1])

            else:
                task_list = handle_cmd(item[0], item[1], process_manager, poller, task_list)
        except queue.Empty:
            pass
        fd_ready = poller.get_process_ready()
        if len(fd_ready) > 0:
            process_manager.handle_read_event(fd_ready)
        # if do_reload % 100 == 0:
        #     task_list = reload_conf('config_test_reload.yml',process_manager, 
        #                 task_list, poller)
        # if do_reload >= 300:
        #     process_manager.start_process('late_start:0')

            # break
        do_reload += 1
    process_manager.stop_all(poller)
    
import shutil
import subprocess
import os


if __name__ == "__main__":
    main()
    """Get the number of open file descriptors for the current process."""
   