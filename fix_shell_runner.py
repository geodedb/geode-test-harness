import sys

with open('runners/shell_runner.py', 'r') as f:
    text = f.read()

text = text.replace(
    '        # Use --plain mode for automated testing - disables terminal control sequences\n'
    '        # that interfere with output capture. Also use table format for easier parsing.\n'
    '        cmd = f"{self.geode_binary} shell --server {self.server} --insecure --format table --no-history --plain"',
    '        # Use --plain mode for automated testing - disables terminal control sequences\n'
    '        # that interfere with output capture. Also use json format for reliable parsing.\n'
    '        cmd = f"{self.geode_binary} shell --server {self.server} --insecure --format json --no-history --plain"'
)

text = text.replace(
    '            # Strip ANSI escape codes\n'
    '            output = self.strip_ansi(raw_output)\n'
    '\n'
    '            # The output contains: echoed command + newline + actual output\n'
    '            # Find and remove the echoed command\n'
    '            lines = output.split("\\n")\n'
    '\n'
    '            # Find where the echoed command ends\n'
    '            cmd_prefix = command.strip()[:20] if len(command) > 20 else command.strip()\n'
    '            output_start = 0\n'
    '            for i, line in enumerate(lines):\n'
    '                if cmd_prefix in line:\n'
    '                    output_start = i + 1\n'
    '                    break\n'
    '\n'
    '            # Get the actual output (everything after the echoed command)\n'
    '            output_lines = lines[output_start:]\n'
    '\n'
    '            # Clean up: remove empty lines at start/end\n'
    '            while output_lines and not output_lines[0].strip():\n'
    '                output_lines.pop(0)\n'
    '            while output_lines and not output_lines[-1].strip():\n'
    '                output_lines.pop()\n'
    '\n'
    '            output = "\\n".join(output_lines)\n'
    '            self.log(\n'
    '                f"Output: {output[:200]}..."\n'
    '                if len(output) > 200\n'
    '                else f"Output: {output}"\n'
    '            )\n'
    '            return True, output',
    '            # Strip ANSI escape codes\n'
    '            output = self.strip_ansi(raw_output).strip()\n'
    '            \n'
    '            # Since we switched to JSON output parsing, we no longer need to fragilely\n'
    '            # match the echoed command line by line. The JSON parser will naturally \n'
    '            # ignore the echoed command which precedes the JSON block.\n'
    '\n'
    '            self.log(\n'
    '                f"Output: {output[:200]}..."\n'
    '                if len(output) > 200\n'
    '                else f"Output: {output}"\n'
    '            )\n'
    '            return True, output'
)

old_check_persistence = '''            elif step_type == "check_persistence_file":
                # Check that the persistence file exists and has data
                persistence_file = os.path.join(self.data_dir, "graph_store.dat")

                if not self.check_file_exists(persistence_file):
                    result["status"] = "failed"
                    result["error"] = f"Persistence file not found: {persistence_file}"
                    return result

                file_size = self.get_file_size(persistence_file)
                result["details"]["persistence_file_size"] = file_size

                min_size = step.get("min_size", 0)
                if file_size < min_size:
                    result["status"] = "failed"
                    result["error"] = (
                        f"Persistence file too small: {file_size} < {min_size}"
                    )
                    return result'''

new_check_persistence = '''            elif step_type == "check_persistence_file":
                # Check that the persistence files exist and have data
                persistence_files = step.get("files", ["graph_store.dat"])
                total_size = 0

                for filename in persistence_files:
                    persistence_file = os.path.join(self.data_dir, filename)

                    if not self.check_file_exists(persistence_file):
                        # Some versions might put files in subdirectories or different names,
                        # this provides a basic check but can be customized via spec
                        result["status"] = "failed"
                        result["error"] = f"Persistence file not found: {persistence_file}"
                        return result

                    file_size = self.get_file_size(persistence_file)
                    result["details"][f"persistence_file_size_{filename}"] = file_size
                    total_size += file_size

                min_size = step.get("min_size", 0)
                if total_size < min_size:
                    result["status"] = "failed"
                    result["error"] = (
                        f"Persistence files total size too small: {total_size} < {min_size}"
                    )
                    return result'''
text = text.replace(old_check_persistence, new_check_persistence)

with open('runners/shell_runner.py', 'w') as f:
    f.write(text)
