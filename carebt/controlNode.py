# Copyright 2021 Andreas Steck (steck.andi@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from abc import ABC

import re

from typing import Callable
from typing import final
from typing import TYPE_CHECKING

from carebt.executionContext import ExecutionContext
from carebt.nodeStatus import NodeStatus
from carebt.treeNode import TreeNode

if TYPE_CHECKING:
    from carebt.behaviorTreeRunner import BehaviorTreeRunner  # pragma: no cover


class ControlNode(TreeNode, ABC):
    """
    `ControlNode` is the basic class for all nodes in careBT which provide a
    control flow functionality, like `SequenceNode`and `ParallelNode`.

    """

    def __init__(self, bt_runner: 'BehaviorTreeRunner', params: str = None):
        super().__init__(bt_runner, params)

        # list for the child nodes
        self._child_ec_list = []

        # the current child pointer
        self._child_ptr = 0

        self._contingency_handler_list = []

        self.set_status(NodeStatus.IDLE)

    # PROTECTED

    def _internal_bind_in_params(self, child_ec: ExecutionContext) -> None:
        if(len(child_ec.call_in_params) != len(child_ec.instance._internal_get_in_params())):
            self.get_logger().warn('{} takes {} argument(s), but {} was/were provided'
                                   .format(child_ec.node.__name__,
                                           len(child_ec.instance._internal_get_in_params()),
                                           len(child_ec.call_in_params)))
        for i, var in enumerate(child_ec.call_in_params):
            if(isinstance(var, str) and var[0] == '?'):
                var = var.replace('?', '_', 1)
                var = getattr(self, var)
            setattr(child_ec.instance,
                    child_ec.instance._internal_get_in_params()[i].replace('?', '_', 1), var)

    def _internal_bind_out_params(self, child_ec: ExecutionContext) -> None:
        for i, var in enumerate(child_ec.instance._internal_get_out_params()):
            var = var.replace('?', '_', 1)
            if(len(child_ec.call_out_params) <= i):
                self.get_logger().warn('{} output {} not provided'
                                       .format(child_ec.node.__name__, i))
            else:
                if(getattr(child_ec.instance, var) is None):
                    self.get_logger().warn('{} output {} is not set'
                                           .format(child_ec.node.__name__,
                                                   var.replace('_', '?', 1)))
                    setattr(self, child_ec.call_out_params[i].replace('?', '_', 1), None)
                else:
                    setattr(self, child_ec.call_out_params[i].replace('?', '_', 1),
                            getattr(child_ec.instance, var))

    @final
    def _internal_tick_child(self, child_ec: ExecutionContext):

        # if child status is IDLE or RUNNING -> tick it
        if(child_ec.instance.get_status() == NodeStatus.IDLE or
           child_ec.instance.get_status() == NodeStatus.RUNNING):
            # tick child
            child_ec.instance._internal_on_tick()

    @final
    def _internal_apply_contingencies(self, child_ec: ExecutionContext):
        self.get_logger().debug('searching contingency-handler for: {} - {} - {}'
                                .format(child_ec.instance.__class__.__name__,
                                        child_ec.instance.get_status(),
                                        child_ec.instance.get_contingency_message()))

        # iterate over contingency_handler_list
        for contingency_handler in self._contingency_handler_list:

            # handle regex
            if(isinstance(contingency_handler[0], str)):
                regexClassName = re.compile(contingency_handler[0])
            else:
                regexClassName = re.compile(contingency_handler[0].__name__)
            regexMessage = re.compile(contingency_handler[2])

            self.get_logger().debug('checking contingency_handler: {} -{} - {}'
                                    .format(regexClassName.pattern,
                                            contingency_handler[1],
                                            regexMessage.pattern))
            # check if contingency-handler matches
            if(bool(re.match(regexClassName,
                             child_ec.instance.__class__.__name__))
                    and child_ec.instance.get_status() in contingency_handler[1]
                    and bool(re.match(regexMessage,
                                      child_ec.instance.get_contingency_message()))):
                self.get_logger().info('{} -> run contingency_handler {}'
                                       .format(child_ec.instance.__class__.__name__,
                                               contingency_handler[3]))
                # execute function attached to the contingency-handler
                exec('self.{}()'.format(contingency_handler[3]))
                self.get_logger().debug('after contingency_handler {} - {} - {}'
                                        .format(child_ec.instance.__class__.__name__,
                                                child_ec.instance.get_status(),
                                                child_ec.instance.get_contingency_message()))
                break

    # PUBLIC

    @final
    def register_contingency_handler(self,
                                     node: TreeNode,
                                     node_status_list: NodeStatus,
                                     contingency_message: str,
                                     contingency_function: Callable) -> None:
        """
        Registers a function which is called in case the provided contingency information
        are met. The registered contingency handlers are tried to match to the current
        status and contingency message in the order they are registered.

        For the parameters `node` and `contingency_message` a regular expression (regex)
        can be used.

        Parameters
        ----------
        node: TreeNode, str
            The node the contingency handler triggered on. In case of using regex
            the name has to be provided as string.
        node_status_list:  [NodeStatus]
            A list of NodeStatus the contingency handler is triggered on
        contingency_message: str
            A regex the contingency-message has to match
        contingency_function: Callable
            The function which should be called

        """

        # for the function only store the name, thus there is no 'bound method' to self
        # which increases the ref count and prevents the gc to delete the object
        self._contingency_handler_list.append((node,
                                               node_status_list,
                                               contingency_message,
                                               contingency_function.__name__))

    @final
    def fix_current_child(self) -> None:
        """
        Mark the current child node as `FIXED`. This function should be called inside
        of a contingency handler in case the handler fixes the situation and the
        control flow of the current `ControlNode` can be continued.

        """

        self.get_logger().trace('{} -> fix_current_child called'
                                .format(self.__class__.__name__))
        self._child_ec_list[self._child_ptr].instance.set_status(NodeStatus.FIXED)

    @final
    def abort_current_child(self) -> None:
        """
        Abort the currently executing child.

        """

        self.get_logger().trace('{} -> abort_current_child called'
                                .format(self.__class__.__name__))
        self._child_ec_list[self._child_ptr].instance.abort()
