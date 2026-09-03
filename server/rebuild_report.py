#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from analysis import ensure_experience_solution
from renderer import render


def main():
    parser = argparse.ArgumentParser(description='从已有分析 JSON 重建完整事实报告，不调用模型 API。')
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    source = args.input.resolve()
    analysis = json.loads(source.read_text('utf-8'))
    result = ensure_experience_solution(analysis)
    output = (args.output or source.with_name(source.stem + '_fixed.html')).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(result, source.stem), 'utf-8')
    output.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(output)


if __name__ == '__main__':
    main()
