from abstract_utilities import *
dirs,files = get_files_and_dirs(get_caller_dir(),allowed_exts=[".py"])
CALL_KEYS = ["post","get","delete"]
def is_strings_in_string(string,keys=CALL_KEYS):
    for key in keys:
        key_str = f".{key}("
        if key_str in string:
            string = string.replace(key_str,".route(")
            string = eatAll(string,")")
            string = f'{string}, methods=["{key.upper()}"])'
            break
    return string
def change_flask_from_fast():
    for file in files:
        contents = read_from_file(file)
        lines = contents.split('\n')
        for i,line in enumerate(lines):
            if line.startswith('@'):
                line = is_strings_in_string(line)
            lines[i] = line
        contents = "\n".join(lines)
        write_to_file(contents=contents,file_path=file)

def change_llm_storage_fast():
    for file in files:
        contents = read_from_file(file)
        lines = contents.split('\n')
        for i,line in enumerate(lines):
            if 'llm_storage' in line:
                line = line.replace("llm_storage","llm_storage")
            lines[i] = line
        contents = "\n".join(lines)
        write_to_file(contents=contents,file_path=file)

change_llm_storage_fast()
