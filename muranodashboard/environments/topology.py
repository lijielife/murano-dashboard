#    Copyright (c) 2014 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import types

from django.contrib.staticfiles.templatetags.staticfiles import static
from django.core.urlresolvers import reverse
from django.template import loader

from muranodashboard.api import packages as pkg_cli


def get_app_image(request, app_fqdn):
    package = pkg_cli.app_by_fqn(request, app_fqdn)
    url = static('dashboard/img/stack-green.svg')
    if package:
        app_id = package.id
        url = reverse("horizon:murano:catalog:images", args=(app_id,))
    return url


def _get_environment_status_message(entity):
    if hasattr(entity, 'status'):
        status = entity.status
    else:
        status = entity['?']['status']

    in_progress = True
    status_message = ''
    if status in ('pending', 'ready'):
        in_progress = False
    if status == 'pending':
        status_message = 'Waiting for deployment'
    elif status == 'ready':
        status_message = 'Deployed'
    elif status == 'deploying':
        status_message = 'Deployment is in progress'
    return in_progress, status_message


def _truncate_type(type_str, num_of_chars):
    if len(type_str) < num_of_chars:
        return type_str
    else:
        parts = type_str.split('.')
        type_str, type_len = parts[-1], len(parts[-1])
        for part in reversed(parts[:-1]):
            if type_len + len(part) + 1 > num_of_chars:
                return '...' + type_str
            else:
                type_str = part + '.' + type_str
                type_len += len(part) + 1
        return type_str


def _application_info(application, app_image, status):
    context = {'name': application['name'],
               'type': _truncate_type(application['?']['type'], 45),
               'status': status,
               'app_image': app_image}
    return loader.render_to_string('services/_application_info.html',
                                   context)


def _network_info(name, image):
    context = {'name': name,
               'image': image}
    return loader.render_to_string('services/_network_info.html',
                                   context)


def _unit_info(unit, unit_image):
    data = dict(unit)
    data['type'] = _truncate_type(data['type'], 45)
    context = {'data': data,
               'unit_image': unit_image}

    return loader.render_to_string('services/_unit_info.html', context)


def _environment_info(environment, status):
    context = {'name': environment.name,
               'status': status}
    return loader.render_to_string('services/_environment_info.html',
                                   context)


def _create_empty_node():
    node = {
        'name': '',
        'status': 'ready',
        'image': '',
        'image_size': 60,
        'required_by': [],
        'image_x': -30,
        'image_y': -30,
        'text_x': 40,
        'text_y': ".35em",
        'link_type': "relation",
        'in_progress': False,
        'info_box': ''
    }
    return node


def _create_ext_network_node(name):
    node = _create_empty_node()
    node.update({'id': name,
                 'image': static('muranodashboard/images/ext-net.png'),
                 'link_type': 'relation',
                 'info_box': _network_info(name, static(
                     'dashboard/img/lb-green.svg'))}
                )
    return node


def _split_seq_by_predicate(seq, predicate):
    holds, not_holds = [], []
    for elt in seq:
        if predicate(elt):
            holds.append(elt)
        else:
            not_holds.append(elt)
    return holds, not_holds


def _is_atomic(elt):
    key, value = elt
    return not isinstance(value, (types.DictType, types.ListType))


def check_service_references(node, node_data, srv_list):
    node_id = node_data['?']['id']
    for service in srv_list:
        for k, v in service.iteritems():
            if v == node_id:
                node['required_by'].append(service['?']['id'])
                node['link_type'] = 'relation'


def render_d3_data(request, environment):
    if not environment:
        return None

    ext_net_name = None
    d3_data = {"nodes": [], "environment": {}}

    in_progress, status_message = _get_environment_status_message(environment)
    environment_node = _create_empty_node()
    environment_node.update({
        'id': environment.id,
        'name': environment.name,
        'status': status_message,
        'image': static('dashboard/img/stack-green.svg'),
        'in_progress': in_progress,
        'info_box': _environment_info(environment, status_message)
    })
    d3_data['environment'] = environment_node

    unit_image_active = static('dashboard/img/server-green.svg')
    unit_image_non_active = static('dashboard/img/server-gray.svg')

    for service in environment.services:
        in_progress, status_message = _get_environment_status_message(service)
        required_by = None
        if 'instance' in service and service['instance'] is not None:
            if service['instance'].get('assignFloatingIp', False):
                if ext_net_name:
                    required_by = ext_net_name
                else:
                    ext_net_name = 'External_Network'
                    ext_network_node = _create_ext_network_node(ext_net_name)
                    d3_data['nodes'].append(ext_network_node)
                    required_by = ext_net_name

        service_node = _create_empty_node()
        service_image = get_app_image(request, service['?']['type'])
        service_node.update({
            'name': service.get('name', ''),
            'status': status_message,
            'image': service_image,
            'id': service['?']['id'],
            'link_type': 'relation',
            'in_progress': in_progress,
            'info_box': _application_info(
                service, service_image, status_message)
        })
        if required_by:
            service_node['required_by'].append(required_by)
        check_service_references(service_node, service, environment.services)
        d3_data['nodes'].append(service_node)

        def rec(node_data, node_key, parent_node=None):
            if not isinstance(node_data, types.DictType):
                return
            node_type = node_data.get('?', {}).get('type')
            atomics, containers = _split_seq_by_predicate(
                node_data.iteritems(), _is_atomic)
            if node_type and node_data is not parent_node:
                node = _create_empty_node()
                atomics.extend([('id', node_data['?']['id']),
                                ('type', node_type),
                                ('name', node_data.get('name', node_key))])
                if parent_node is not None:
                    node['required_by'].append(parent_node['?']['id'])
                if len(node_data.get('ipAddresses', [])) > 0:
                    image = unit_image_active
                else:
                    image = unit_image_non_active
                node.update({
                    'id': node_data['?']['id'],
                    'info_box': _unit_info(atomics, image),
                    'image': image,
                    'link_type': 'unit',
                    'in_progress': in_progress})
                d3_data['nodes'].append(node)

            for key, value in containers:
                if key == '?':
                    continue
                if isinstance(value, types.DictType):
                    rec(value, key, node_data)
                elif isinstance(value, types.ListType):
                    for index, val in enumerate(value):
                        rec(val, '{0}[{1}]'.format(key, index), node_data)

        rec(service, None, service)

    return json.dumps(d3_data)
