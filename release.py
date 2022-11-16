import argparse
import os
import re
import shutil
import subprocess
import sys
import yaml

base_dir = os.getcwd()
release_info = {}


def checkout_helm_charts():
    apps = release_info['apps']
    os.chdir(os.path.join(base_dir, release_info['release_dir']))
    for app in apps:
        if app.get('is-chart', False):
            for component in app['components']:
                checkout_component('tag', app, component)


def checkout_component(git_type, app, component):
    component_name = component['name']
    app_name = app['name']
    print(f'checkout {git_type}: {app_name}-{component_name}')
    if app.get('skip', False):
        return
    dir_name = f'{app_name}-{component_name}'
    git_info = get_branch_tag_info(git_type, component)

    try:
        exists = os.path.isdir(os.path.join(base_dir, release_info['release_dir'], dir_name))
        start_tag = git_info['start']
        if exists:
            subprocess.check_call([f'git checkout {start_tag}'], shell=True,
                                  cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    except subprocess.CalledProcessError:
        sys.exit(f'Unable to checkout repo: {app_name}/{component_name}')


def fetch_origin(component_name, app_name, dir_name):
    try:
        print(f'\tpull {app_name}/{component_name}')
        subprocess.check_call(['git fetch --depth 1 origin'], cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                              shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        sys.exit(f'Unable to update repo: {app_name}/{component_name}')


def clone_repo(app, component):
    if app.get('skip', False):
        return
    component_name = component['name']
    app_name = app['name']
    should_fetch = component.get('fetch', release_info.get('fetch', False))
    should_clone = component.get('clone', release_info.get('clone', False))
    dir_name = f'{app_name}-{component_name}'
    try:
        exists = os.path.isdir(os.path.join(base_dir, release_info['release_dir'], dir_name))
        if not exists:
            if should_clone:
                app_git_root_suffix = app['git_root_suffix']
                
                cmd = f'git clone --depth 1 {gitlab_url}/{app_git_root_suffix}/{component_name}.git  {dir_name}'
                print(f'\tcloning {app_name}/{component_name}')

                subprocess.check_output([cmd], shell=True,
                                                  cwd=os.path.join(base_dir, release_info['release_dir']),
                                                  stderr=subprocess.STDOUT)
            else:
                print(f'\tskip clone {app_name}-{component_name}')
        else:
            if should_fetch:
                fetch_origin(component_name, app_name, dir_name)
            else:
                print(f'\tskip clone {component_name}')
    except subprocess.CalledProcessError as e:
        print("Exception on process, rc=", e.returncode, "output=", e.output)
        sys.exit(f'Unable to clone repo: {app_name}/{component_name}')


def get_repos():
    apps = release_info['apps']
    os.chdir(os.path.join(base_dir, release_info['release_dir']))
    for app in apps:
        for component in app['components']:
            # If the directory does not exist, clone the project
            if not os.path.exists(os.path.join(base_dir, release_info['release_dir'], app['name'])):
                clone_repo(app, component)


def get_charts():
    print(f'clone charts')
    apps = release_info['apps']
    for app in apps:
        if app.get('is-chart', False):
            for component in app['components']:
                # If the directory does not exist, clone the project
                print(f'get chart component:{component}')
                print(f"exists: {os.path.exists(os.path.join(base_dir, release_info['release_dir'], app['name']))}")
                if not os.path.exists(os.path.join(base_dir, release_info['release_dir'], app['name'])):
                    clone_repo(app, component)


def diff_apps():
    change_name = release_info.get('tag', {}).get('name')
    if not os.path.exists(os.path.join(base_dir, 'changes')):
        os.mkdir(os.path.join(base_dir, 'changes'))

    if os.path.exists(os.path.join(base_dir, 'changes', f'changes-{change_name}')):
        os.remove(os.path.join(base_dir, 'changes', f'changes-{change_name}'))

    changes = open(os.path.join(base_dir, 'changes', f'changes-{change_name}'), "a")
    apps = release_info['apps']
    for app in apps:
        for component in app['components']:
            diff_app(app, component, changes)

    changes.close()


def is_release(tag):
    match = re.search("^v[0-9]+\\.[0-9]+\\.[0-9]+-BETA[0-9]+|release|RC[0-9]+$", tag)
    if match is not None:
        return True
    else:
        return False


def get_latest_tag(app, component):
    component_name = component['name']
    app_name = app['name']
    dir_name = f'{app_name}-{component_name}'
    try:
        cmd = "git tag --sort=committerdate"
        content = subprocess.check_output([cmd], shell=True,
                                          cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                                          stderr=subprocess.STDOUT)
        if content.decode('utf-8'):
            tags = content.decode('utf-8').strip().split()
            filtered = filter(is_release, tags)
            release_tags = []
            for tag in filtered:
                release_tags.append(tag)
            if len(release_tags) > 0:
                return release_tags[len(release_tags) - 2]
            else:
                return None

        else:
            return None
    except subprocess.CalledProcessError as e:
        print(e)
        print(f'{dir_name}: Failed to get recent tag')


def diff_app(app, component, change_file):
    if app.get('skip', False):
        return
    component_name = component['name']
    app_name = app['name']
    dir_name = f'{app_name}-{component_name}'
    exists = os.path.isdir(os.path.join(base_dir, release_info['release_dir'], dir_name))

    if exists:
        latest_tag = get_latest_tag(app, component)
        change_file.write(f'\n\n{app_name}-{component_name} tag: {latest_tag}\n')
        print(f'diff app {app_name} {component_name}')
        try:
            cmd = f'git log --graph --oneline {latest_tag}...HEAD'
            diff = subprocess.check_output([cmd], shell=True,
                                           cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                                           stderr=subprocess.STDOUT)
            if diff.decode('utf-8'):
                change_file.write(f'changes since: {latest_tag}\n')
                change_file.write(diff.decode('utf-8').strip() + '\n')
            else:
                change_file.write(f'No Changes since {latest_tag}\n')
        except subprocess.CalledProcessError:
            print(f'{dir_name}: Failed to get diff for tag {latest_tag}')

    else:
        change_file.write(f'\n{app_name}-{component_name}\n')
        change_file.write('Not cloned\n\n')


def create_release_dir():
    print(f'create release dir {release_info["release_dir"]}')
    if not os.path.exists(os.path.join(base_dir, release_info['release_dir'])):
        print(f'Creating release dir {os.getcwd()}/{release_info["release_dir"]}')
        os.makedirs(os.path.join(base_dir, release_info['release_dir']))


def list_apps():
    if 'apps' in release_info:
        for app in release_info['apps']:
            print(app['name'])
            for component in app['components']:
                print(component)

    else:
        print('No apps in release_info file')


def create_tags(include_charts):
    for app in release_info['apps']:
        for component in app['components']:
            if (app.get('is-chart', False) and include_charts) or not app.get('is-chart', False):
                create_branch_or_tag('tag', app, component)


def create_branches(include_charts):
    for app in release_info['apps']:
        for component in app['components']:
            if (app.get('is-chart', False) and include_charts) or not app.get('is-chart', False):
                create_branch_or_tag('branch', app, component)


def create_branch_or_tag(git_type, app, component):
    if app.get('skip', False):
        return
    component_name = component['name']
    app_name = app['name']
    dir_name = f'{app_name}-{component_name}'
    exists = os.path.isdir(os.path.join(base_dir, release_info['release_dir'], dir_name))
    git_info = get_branch_tag_info(git_type, component)

    if git_info['create']:
        if exists:
            git_name = git_info['name']
            start_tag = git_info['start']
            if git_name is None:
                print(f'No name specified for component or globally for {app_name}/{component_name} type:{git_type}')
                sys.exit()
            else:
                print(f'creating {git_type} {git_name} from {start_tag} for {app_name}/{component_name}')
            try:
                if git_info['create'] and git_type == 'branch':
                    subprocess.check_call([f'git checkout -b {git_name} {start_tag}'], shell=True,
                                          cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if git_type == "tag":
                    subprocess.check_call([f'git checkout {start_tag}'], shell=True,
                                          cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    subprocess.check_call([f'git tag {git_name}'], shell=True,
                                          cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                if git_info['push']:
                    subprocess.check_call([f'git push origin {git_name}'], shell=True,
                                          cwd=os.path.join(base_dir, release_info['release_dir'], dir_name),
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            except subprocess.CalledProcessError:
                print(f'unable to create new {git_type} for repo: {app_name}/{component_name}')


def get_branch_tag_info(git_type, component):
    default_info = release_info.get(git_type, {})
    component_overrides = component.get(git_type, {})
    type_info = {
        'create': component_overrides.get('create', default_info.get('create', False)),
        'start': component_overrides.get('start', default_info.get('start', 'master')),
        'name': component_overrides.get('name', default_info.get('name', None)),
        'push': component_overrides.get('push', default_info.get('push', False))
    }
    return type_info


def remove_release_dir():
    if clean and os.path.exists(os.path.join(base_dir, release_info['release_dir'])):
        print(f'Deleting release dir {os.getcwd()}/{release_info["release_dir"]}')
        shutil.rmtree(os.path.join(base_dir, release_info['release_dir']))


def image_tag_from_git_tag(git_tag):
    return git_tag.replace('-release', '').replace('v', '')


def image_name(component):
    image_path = component.get('image-path', None)
    name = component.get('name')
    if image_path is None:
        if '-' in name:
            values = name.split('-')
            return '.' + values[0] + ''.join(ele.title() for ele in values[1:]) + '.image.tag'
        else:
            return f'.{name}.image.tag'
    else:
        return image_path


def update_helm_chart_versions():
    for app in release_info['apps']:
        chart_path = app.get('chart-path', None)
        tag_name = image_tag_from_git_tag(release_info.get('tag', {}).get('name', 'missing'))
        if app.get('is-chart', False):
            chart_values_file_name = os.path.join(base_dir, release_info['release_dir'], chart_path, 'Chart.yaml')
            try:
                cmd = ['yq', '-i', '.version = ' + '"' + tag_name + '"', chart_values_file_name]
                subprocess.check_call(cmd, shell=False,
                                      cwd=os.path.join(base_dir))
                cmd = ['yq', '-i', '.appVersion = ' + '"' + tag_name + '"', chart_values_file_name]
                subprocess.check_call(cmd, shell=False,
                                      cwd=os.path.join(base_dir))

            except subprocess.CalledProcessError as e:
                print(f'Unable to update Chart version {tag_name} for {app.get("name")}')
                print(e)


def update_helm_chart_image_tags():
    for app in release_info['apps']:
        chart_path = app.get('chart-path', None)
        if chart_path is not None:
            chart_values_file_name = os.path.join(base_dir, release_info['release_dir'], chart_path, 'values.yaml')
            for component in app['components']:
                if not app.get('is-chart', False):
                    git_info = get_branch_tag_info('tag', component)
                    tag_name = image_tag_from_git_tag(git_info.get('name'))
                    image_path = f'{app.get("chart-value-prefix", "")}{image_name(component)}'
                    image_value = image_path + ' = ' + '"' + tag_name + '"'
                    cmd = ['yq', '-i', image_value, chart_values_file_name]
                    try:
                        subprocess.check_call(cmd, shell=False,
                                              cwd=os.path.join(base_dir))

                    except subprocess.CalledProcessError as e:
                        print(f'Unable to replace tag {tag_name} for {app.get("name")}-{component.get("name")}')
                        print(e)


parser = argparse.ArgumentParser(description='Create release for CEQASP')

parser.add_argument('--file', help='Manifest for release info')
parser.add_argument('--clean', default=False, action='store_true', help='Clean release directory')
parser.add_argument('--clone', default=False, action='store_true', help='Clone all projects that have clone: true')
parser.add_argument('--clone-charts', default=False, action='store_true', help='Clone charts that have clone: true')
parser.add_argument('--checkout-charts', default=False, action='store_true', help='Checkout charts using tag branch start: true')
parser.add_argument('--create-release-branch', default=False, action='store_true', required=False, help='Create starting tag and create release branch from that tag')
parser.add_argument('--tag-release-branch', default=False, action='store_true', required=False, help='Create tag on release branch')
parser.add_argument('--diff', default=False, action='store_true', required=False, help='Produce change list for release-branch.  Release branch should already exist and have at least one tag')
parser.add_argument('--update-chart-tags', default=False, action='store_true', required=False, help='Update helm chart image tags')
parser.add_argument('--git-user', help='Git user')
parser.add_argument('--git-password', help='Git password')
args = vars(parser.parse_args())

clean = args.get('clean', False)
clone = args.get('clone', False)
clone_charts = args.get('clone_charts', False)
checkout_charts = args.get('checkout_charts', False)
tag_release_branch = args.get('tag_release_branch', False)
create_release_branch = args.get('create_release_branch', False)
diff = args.get('diff', False)
update_chart_tags = args.get('update_chart_tags', False)
manifest_file = args['file']
git_user = args.get('git_user', None)
git_password = args.get('git_password', None)

if manifest_file is None:
    sys.exit('--file options is required')

if manifest_file is not None:
    print(f'using file {manifest_file}')
    with open(manifest_file, "r") as release_file:
        release_info = yaml.load(release_file, Loader=yaml.FullLoader)

git_domain = release_info.get('git-repo', {}).get('domain', 'gitlab.com')
git_group = release_info.get('git-repo', {}).get('root_path', 'cequence')
gitlab_url = None

if git_user is None:
    print(f'Gitlab credentials not found, assuming ssh protocol')
    gitlab_url = f'git@{git_domain}:{git_group}'
else:
    print(f'Credentials found, using gitlab token to authenticate')
    gitlab_url = f'https://{git_user}:{git_password}@{git_domain}/{git_group}'

if create_release_branch and tag_release_branch:
    sys.exit('--create-release-branch cannot be combined with --tag-release-branch')

if clean:
    remove_release_dir()

create_release_dir()

# list_apps()
if clone:
    get_repos()

if create_release_branch:
    create_tags(True)
    create_branches(True)

if tag_release_branch:
    create_tags(False)

if clone_charts:
    get_charts()

if checkout_charts:
    checkout_helm_charts()

if update_chart_tags:
    update_helm_chart_image_tags()
    update_helm_chart_versions()

if diff:
    diff_apps()
